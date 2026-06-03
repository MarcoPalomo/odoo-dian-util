# Architecture — Pipeline Odoo 17 / Document Automation (Colombie)

> Contexte : automatisation de flux clients à partir de documents colombiens (RUT, factures)
> vers Odoo 17 Enterprise sur Odoo.sh, avec monitoring de processus de bout en bout.
>
> Instance : `industriaspico-industriaspico.odoo.com`
> Base de données : `industriaspico-industriaspico-main-14967325`

---

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────┐
│                        INGESTION LAYER                          │
│  Odoo Documents (workspace "RUTs Clientes") │ CLI local         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      STORAGE RAW (immuable)                     │
│  Odoo Documents  →  odoo://documents.document/{id}              │
│  MinIO / S3      →  {year}/{month}/{doc_id}/{filename}          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     EXTRACTION WORKER                           │
│  pdfplumber (PDFs natifs DIAN)                                  │
│  ├── Routing persona natural (champ 24) / jurídica (champ 35)   │
│  ├── score de confiance par champ                               │
│  ├── NIT validator (algo DV colombien)                          │
│  ├── résultat structuré Pydantic                                │
│  └── si confidence < 0.92 → Human Review Queue                  │
└──────────┬───────────────────────────┬──────────────────────────┘
           │ confidence >= 0.92        │ confidence < 0.92
           ▼                           ▼
┌──────────────────┐        ┌──────────────────────────────────┐
│  AUTO PIPELINE   │        │   HUMAN-IN-THE-LOOP (HITL)       │
│  [opérationnel]  │        │   Tag "To Validate" dans Odoo    │
│                  │        │   Documents — Sprint 2            │
└────────┬─────────┘        └──────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    VALIDATION LAYER                             │
│  ├── NIT : DV algorithmique (poids DIAN)                        │
│  ├── Dedup : search sur champ vat                               │
│  └── Champs obligatoires : vat + razón social                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ODOO INTEGRATION LAYER                        │
│  XML-RPC natif — DB: industriaspico-industriaspico-main-14967325│
│  ├── upsert idempotent sur champ vat                            │
│  ├── tags : Cliente/Proveedor + B2B + Import_Auto               │
│  └── retry × 3 avec backoff exponentiel                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              INTELLIGENCE FISCALE + PRÉ-QUALIFICATION           │
│  ├── Extraction CIIU + responsabilidades DIAN du texte RUT      │
│  ├── Note HTML chatter sur res.partner (profil fiscal, DV)      │
│  ├── Score 0–100 : signaux RUT (60 max) + DIAN (20) + RUES (20)│
│  ├── Oportunidad CRM [VERDE/AMARILLO/ROJO] pour Hector          │
│  └── Si sources indisponibles → AMARILLO + retry J+1 planifié   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AUDIT LOG (PostgreSQL séparé)                │
│  pipeline_audit_log : doc_id, source, nit_valid, action…        │
│  prequal_retries    : nit, fuentes_fallidas, retry_after        │
│  → conformité Ley 1581 (données personnelles colombiennes)      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼ (lecture seule)
┌─────────────────────────────────────────────────────────────────┐
│               PIPELINE CRM ODOO (existant, intact)              │
│  New → Qualified → Diseño → Ajustes → Proposition →             │
│  Negociación → Won → Producción → Entrega → Novedades →         │
│  Facturación                                                    │
│  Facturation électronique DIAN : Carvajal (déjà opérationnel)  │
└─────────────────────────────────────────────────────────────────┘
```

---

## État des modules (2026-06-03)

| Module | Fichier | Statut |
|---|---|---|
| Extraction RUT | `extraction/pdfplumber_extractor.py` | ✅ Persona natural + jurídica |
| Validateur NIT | `nit_validator.py` | ✅ 15 tests |
| Gate confiance | `gates/confidence_gate.py` | ✅ Opérationnel |
| Gate NIT | `gates/nit_gate.py` | ✅ Opérationnel |
| Gate champs | `gates/fields_gate.py` | ✅ Opérationnel |
| Client Odoo | `odoo_client.py` | ✅ Upsert + CRM leads + retry update |
| Storage MinIO | `storage_client.py` | ✅ Opérationnel |
| Intelligence fiscale | `fiscal_intelligence.py` | ✅ Opérationnel |
| Pré-qualification | `prequalification.py` | ✅ AMARILLO provisional si sources down |
| Retry store | `retry_store.py` | ✅ PostgreSQL, retry J+1 |
| Audit log | `audit_log.py` | ✅ No-op si AUDIT_DB_DSN absent |
| Orchestrateur | `runner.py` | ✅ Opérationnel |
| Ingestion Documents | `scripts/ingest_from_documents.py` | ✅ Workspace 196 |
| Retry pré-qual | `scripts/retry_prequalification.py` | ✅ Opérationnel |
| Queue Redis | — | 🔜 Sprint 2 |
| HITL FastAPI/HTMX | — | 🔜 Sprint 2 |

**Test réel effectué** (2026-06-03) : 16 documents traités depuis Odoo Documents
- Personas jurídicas : extraction champ 35 (Razón Social)
- Personas naturales : routing champ 24 → champs 31-34 (nom complet sans duplication)
- Retry planifié pour DIAN/RUES (sources en maintenance au moment du test)

---

## Contexte instance réelle (vérifié le 2026-05-23)

| Donnée | Valeur |
|---|---|
| Version Odoo | 17.0 Enterprise |
| Base de données | `industriaspico-industriaspico-main-14967325` |
| Contacts total | ~2 868 |
| Contacts Colombie | ~2 114 |
| Facturation DIAN | Carvajal (`l10n_co_edi`) — déjà opérationnel |
| Pipeline CRM | 11 étapes de New à Facturación |
| `country_id` Colombie | **49** (stable sur l'instance) |
| `l10n_latam_identification_type_id` NIT | **4** (vérifié — pas 31) |
| `l10n_co_edi_fiscal_regimen` valeurs | `'48'`=IVA, `'49'`=No Aplica, `'04'`=INC, `'ZA'`=IVA+INC |
| Tag `Import_Auto` | id=15 (créé en Sprint 1) |
| Workspace RUTs | `documents.folder` id=196 ("RUTs Clientes") |
| Tags Documents | id=1 Inbox, id=2 To Validate, id=3 Validated |

---

## Couches détaillées

### 1. Ingestion Layer

| Canal | Mécanisme | Statut |
|---|---|---|
| Odoo Documents | `scripts/ingest_from_documents.py` — workspace id=196 | ✅ Opérationnel |
| CLI local | `scripts/process_rut.py` — `make run PDF=...` | ✅ Opérationnel |
| Email | Alias dédié (`rut@...`) → parsing MIME | 🔜 Sprint 2 |
| WhatsApp Business | API Meta → webhook | 🔜 Sprint 3 |

Chaque document entrant reçoit un `doc_id` (UUID v4) **avant traitement**. Pour les documents Odoo, le `s3_path` est `odoo://documents.document/{id}` — MinIO n'est pas utilisé.

---

### 2. Storage Raw

- **Odoo Documents** (mode principal) : référence `odoo://documents.document/{id}` — le document reste dans Odoo
- **MinIO / S3** (mode CLI) : `{year}/{month}/{doc_id}/{filename}` avec métadonnées source/sha256
- **Rétention :** illimitée (Ley 1581 + obligation fiscale colombienne)

---

### 3. Extraction Worker

**Routing persona natural / jurídica :**

```
Champ 24 "Tipo contribuyente"
  ├── contient "natural"  → champs 31 + 32 + 33 + 34 (apellidos + nombres, dédupliqués)
  ├── contient "jurídica" → champ 35 (Razón Social)
  └── non trouvé          → champ 35, fallback 31-34
```

**Champs extraits (vérifiés sur l'instance Odoo) :**

| Champ Odoo | Source RUT | Champ DIAN | Obligatoire |
|---|---|---|---|
| `vat` | NIT (sans DV) | Table NIT en-tête | Oui |
| `name` | Razón Social ou nom complet | 35 (jurídica) / 31-34 (natural) | Oui |
| `l10n_latam_identification_type_id` | Type documento → `id=4` (NIT) | — | Oui (défaut) |
| `l10n_co_edi_fiscal_regimen` | Codes 48/04 → `'48'`/`'04'`/`'ZA'`/`'49'` | Responsabilidades | Non |
| `l10n_co_edi_commercial_name` | Nombre comercial | 36 | Non |
| `email` | Correo electrónico DIAN | 42 | Non |
| `street` | Dirección principal | 41 | Non |
| `city` | Municipio | 38 (dernier mot) | Non |

---

### 4. Pré-qualification

**Scoring :**

```
Sources internes (cap 60 pts)      Sources externes (40 pts max)
────────────────────────────       ─────────────────────────────
Code 15 Autorretenedor  +40        DIAN estado = Activo    +20
Code 52 Facturador      +10        RUES capital ≥ 150M COP +20
Code 10 Aduanero        +10        DIAN estado Cancelado   -40
Code 42 Contabilidad    + 5
Code 22/23 Import/Export + 5 chacun
Code 41 Activos ext.    + 5
RUT mis à jour < 3 ans  + 5
```

**Semáforo :**

| Score | Couleur | Condition |
|---|---|---|
| ≥ 60 | 🟢 VERDE | Score atteint même sans sources externes |
| 35–59 | 🟡 AMARILLO | Score intermédiaire ou sources indisponibles |
| < 35 | 🔴 ROJO | Score bas confirmé OU RUT Cancelado/Suspendido |

> ROJO seulement sur négatif **confirmé** — jamais sur absence de données.

**Retry différé J+1 :**

Quand DIAN ou RUES sont indisponibles, le pipeline sauvegarde dans `prequal_retries` :
- `nit`, `partner_id`, `lead_id`, `fuentes_fallidas`, `score_partiel`, `semaforo_prev`
- `retry_after = NOW() + 1 day`

`make prequal-retry` (ou cron quotidien) recharge uniquement les sources qui avaient échoué et met à jour la lead CRM si le semáforo change.

---

### 5. Audit Log

Base PostgreSQL **séparée** de la BDD Odoo — no-op silencieux si `AUDIT_DB_DSN` absent.

**Table principale :**
```sql
CREATE TABLE pipeline_audit_log (
    id                    BIGSERIAL PRIMARY KEY,
    doc_id                TEXT NOT NULL,
    source                TEXT,           -- 'email' | 'upload' | 'whatsapp'
    raw_s3_path           TEXT,           -- 'odoo://documents.document/{id}' ou chemin MinIO
    extraction_engine     TEXT,           -- 'pdfplumber'
    extraction_confidence FLOAT,
    nit_extracted         TEXT,
    nit_valid             BOOLEAN,
    needs_hitl            BOOLEAN,
    hitl_operator         TEXT,
    odoo_partner_id       INTEGER,
    odoo_action           TEXT,           -- 'created' | 'updated' | 'skipped' | 'failed'
    error_message         TEXT,
    duration_ms           INTEGER,
    created_at            TIMESTAMPTZ DEFAULT NOW()
);
```

**Table retry :**
```sql
CREATE TABLE prequal_retries (
    id               BIGSERIAL PRIMARY KEY,
    nit              TEXT NOT NULL,
    partner_id       INTEGER,
    lead_id          INTEGER,
    fuentes_fallidas TEXT[],
    score_partiel    INTEGER,
    semaforo_prev    TEXT,
    retry_after      TIMESTAMPTZ NOT NULL,
    retried_at       TIMESTAMPTZ
);
```

---

### 6. Pipeline CRM existant (ne pas modifier)

```
New → Qualified → Diseño → Ajustes → Proposition →
Negociación → Won → Producción → Entrega → Novedades → Facturación
```

Le pipeline d'import interagit avec le CRM à **deux points seulement** :
1. Upsert du contact `res.partner` (avec tags, régimen, email, adresse)
2. Création d'une oportunidad `crm.lead` en étape *New* pour la pré-qualification

Les étapes CRM et la configuration Carvajal ne sont jamais touchées.

---

## Stack technique

| Composant | Technologie | Justification |
|---|---|---|
| Runtime | Python 3.12 | Compatibilité librairies |
| Storage principal | Odoo Documents | Documents déjà dans Odoo — pas de MinIO requis |
| Storage archive | MinIO / S3 | Immuabilité, Ley 1581 (mode CLI) |
| Extraction PDF | `pdfplumber` | Gratuit, ~99% sur PDFs natifs DIAN |
| Validation | Pydantic v2 | Strict, erreurs lisibles |
| Retry Odoo | `tenacity` | Standard Python |
| Odoo API | XML-RPC natif | Aucune dépendance externe |
| Audit / Retry | PostgreSQL séparé | Requêtable, séparé d'Odoo |
| Logs | `structlog` JSON | Machine-readable |

---

## Garanties de l'architecture

| Propriété | Garantie |
|---|---|
| Doublon contact Odoo | Bloqué par upsert idempotent sur `vat` |
| NIT invalide accepté | Bloqué par validation DV algorithmique |
| Faux ROJO sur sources indisponibles | Impossible — AMARILLO provisional jusqu'au retry |
| Nom persona natural dupliqué | Impossible — déduplication après extraction champs 31-34 |
| Audit Ley 1581 | Chaque opération tracée avec timestamp et durée |
| Failure Odoo API | Retry × 3 avec backoff exponentiel |
| Facturation DIAN cassée | Impossible — Carvajal jamais touché par le pipeline |
| Source externe en panne | Graceful degradation + retry J+1 automatique |
