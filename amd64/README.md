# RUT Pipeline — Linux x86\_64

Automatisation d'import de documents colombiens (RUT DIAN) vers Odoo 17 Enterprise.
Instance cible : `industriaspico-industriaspico.odoo.com`

← [Retour au README principal](../README.md)

---

## Prérequis

| Outil | Version min | Usage |
|---|---|---|
| Python | 3.11 | Runtime |
| Docker | récent | PostgreSQL + MinIO + Redis (infra locale) |

> **Sans infra locale ?** Utilise `--dry-run` pour tester l'extraction et les gates sans aucune écriture.

---

## Installation

```bash
make install
```

---

## Configuration

Édite `.env` :

```env
# Odoo XML-RPC
ODOO_URL=https://industriaspico-industriaspico.odoo.com
ODOO_DB=industriaspico-industriaspico-main-14967325
ODOO_USER=ton_user@industriaspico.com
ODOO_PASSWORD=ton_mot_de_passe

# PostgreSQL — base dédiée, séparée d'Odoo
AUDIT_DB_DSN=postgresql://pipeline:pipeline@localhost:5432/pipeline_audit

# MinIO (optionnel — non requis pour l'ingestion Documents)
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=rut-documents
MINIO_SECURE=false

# Seuil de confiance extraction (ne pas modifier sans mesure terrain)
CONFIDENCE_THRESHOLD=0.92
```

---

## Démarrage de l'infra locale

```bash
make infra-up      # Démarre PostgreSQL + Redis + MinIO (Docker)
make db-setup      # Crée la base pipeline_audit + schéma (idempotent)
make odoo-setup    # Crée le tag Import_Auto dans Odoo (one-shot)
```

---

## Mode principal — Ingestion depuis Odoo Documents

Les PDFs RUT sont déposés dans le workspace **"RUTs Clientes"** (id=196) du module Documents Odoo, puis traités automatiquement.

```bash
# Traiter tous les PDFs en attente dans le workspace
make docs-ingest

# Surveiller en continu (poll toutes les 30s)
make docs-watch

# Tester sans écriture dans Odoo
make docs-dry-run

# Réinitialiser les tags du workspace et retraiter tous les documents
make docs-reset
```

**Workflow dans Odoo Documents :**
1. Déposer le PDF RUT dans le workspace "RUTs Clientes"
2. `make docs-ingest` (ou `docs-watch` pour la surveillance continue)
3. Le document est tagué **Validated** et lié au contact créé/mis à jour

---

## Mode secondaire — CLI sur un PDF local

```bash
# Dry-run — extraction + gates uniquement, rien n'est écrit
make dry-run PDF="chemin/vers/rut.pdf"

# Pipeline complet
make run PDF="chemin/vers/rut.pdf"

# RUT fournisseur
python scripts/process_rut.py "rut.pdf" --proveedor

# Avec source déclarée
python scripts/process_rut.py "rut.pdf" --source email
```

---

## Flux complet du pipeline

```
PDF (Odoo Documents ou fichier local)
 │
 ▼
[1] Archivage             ← odoo://documents.document/{id} ou MinIO (règle fondamentale)
 │
 ▼
[2] Extraction pdfplumber ← NIT, razón social, régimen, CIIU… + score de confiance
 │                          Routing persona natural (champ 24) vs jurídica (champ 35)
 ▼
[3] Gate confiance        ← confiance < 0.92 → HITL (tag "To Validate" dans Documents)
 │ pass
 ▼
[4] Gate NIT              ← DV invalide → erreur bloquante
 │ pass
 ▼
[5] Gate champs           ← vat ou name absent → erreur bloquante
 │ pass
 ▼
[6] Upsert Odoo           ← search(vat) avant create — idempotent
 │
 ▼
[7] Intelligence fiscale  ← profil CIIU + responsabilidades DIAN → chatter du contact
 │
 ▼
[8] Pré-qualification     ← semáforo VERDE/AMARILLO/ROJO → oportunidad CRM pour Hector
 │    └─ Si DIAN/RUES indisponibles → AMARILLO + retry J+1 planifié
 ▼
[9] Audit log PostgreSQL  ← écrit dans tous les cas (succès, HITL, erreur)
```

---

## Pré-qualification (auditoría previa)

Score 0–100. Crée une oportunidad CRM en étape *New* pour la décision GO/NO-GO de Hector.

**Signaux internes du RUT (jusqu'à 60 pts) :**

| Signal | Points |
|---|---|
| Autorretenedor (code 15) | 40 |
| Facturador electrónico (code 52) | 10 |
| Obligado aduanero (code 10) | 10 |
| Obligado a llevar contabilidad (code 42) | 5 |
| Importateur/Exportateur (codes 22/23) | 5 chacun |
| Activos en el exterior (code 41) | 5 |
| RUT mis à jour < 3 ans | 5 |

**Sources externes (jusqu'à 40 pts) :**

| Source | Points | Statut |
|---|---|---|
| DIAN — estado Activo | +20 | Intermittent (maintenance MUISCA) |
| RUES — capital ≥ 150 M COP | +20 | Intermittent (migration SPA React) |

**Semáforo :**
- 🟢 **VERDE** (≥ 60) : "Perfil sólido. Proceder a negociación sujeto a aprobación de Hector."
- 🟡 **AMARILLO** (35–59 ou sources indisponibles) : "Solicitar estados financieros antes de negociar."
- 🔴 **ROJO** (< 35 ou RUT Cancelado/Suspendido) : "No proceder sin investigación adicional."

> Un AMARILLO avec sources indisponibles n'est pas un signal négatif — c'est un signal que les données sont incomplètes. Le retry J+1 recalcule quand les sources reviennent.

---

## Retry pré-qualification

Quand DIAN ou RUES sont indisponibles, le contexte est sauvegardé dans `prequal_retries` (PostgreSQL) pour un retry le lendemain à la même heure.

```bash
# Relancer manuellement les retries en attente
make prequal-retry

# Via cron (recommandé — tous les jours à 08h00)
# 0 8 * * * cd /chemin/projet && make prequal-retry >> logs/retry.log 2>&1
```

---

## Tests

```bash
make test    # 15 tests NIT validator + gates
make lint    # ruff check
```

---

## Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| `needs_hitl: True` | Score extraction < 0.92 | Vérifier si le PDF est un scan — pdfplumber ne fait pas d'OCR |
| `NITValidationError` | DV extrait ≠ DV calculé | NIT mal parsé — inspecter `raw_text` dans les logs |
| `MandatoryFieldError` | `vat` ou `name` absent | Regex non matché — inspecter `raw_text` dans les logs |
| `ConnectionError Odoo` | Mauvais credentials | Vérifier `ODOO_USER` / `ODOO_PASSWORD` dans `.env` |
| `audit_write_failed` | PostgreSQL non démarré | `make infra-up && make db-setup` |
| `retry_store_disabled` | `AUDIT_DB_DSN` vide ou table manquante | `rm -f .stamps/db-setup && make db-setup` |
| `dian_viewstate_not_found` | MUISCA en maintenance | Normal — score calculé sans +20 DIAN, retry planifié J+1 |
| `rues_html_response` | RUES SPA répond en HTML | Normal — score calculé sans +20 RUES, retry planifié J+1 |
| `no_pending_documents` | Tous les docs déjà traités | `make docs-reset` pour retraiter |
