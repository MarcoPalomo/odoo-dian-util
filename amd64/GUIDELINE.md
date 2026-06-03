# Guidelines — Pipeline Odoo 17 / Document Automation

> Règles de développement, d'exploitation et de qualité pour l'équipe.
> À lire avant d'écrire la moindre ligne de code.
>
> Instance cible : `industriaspico-industriaspico.odoo.com`
> DB : `industriaspico-industriaspico-main-14967325`

---

## 1. Principes fondamentaux

### Archiver avant de traiter

Tout document entrant est référencé dans le storage raw **avant** toute autre opération. Pour les documents Odoo, la référence est `odoo://documents.document/{id}`. Si le worker plante après l'archivage, le document peut être rejoué. Si le worker plante avant, le document est perdu.

```
CORRECT  : archive/référencer → traitement
INTERDIT : traitement → archive
```

### Le doc_id naît avant tout

L'UUID v4 du document est généré **avant** tout traitement, et passé à toutes les couches suivantes. Un `doc_id=unknown` dans les logs est une anomalie bloquante.

### Jamais de `create` sans `search` d'abord

2 114+ contacts colombiens existent déjà dans Odoo. Un doublon crée des incohérences comptables. La recherche sur `vat` est obligatoire avant toute création.

### Toute extraction est scorée

Chaque champ extrait a un score de confiance `[0.0, 1.0]`. Un résultat sans score n'est pas un résultat valide.

### Le pipeline ne cache jamais ses erreurs

Si un document échoue, il est marqué avec un message d'erreur explicite dans l'audit log et le tag Documents revient à l'état sans tag validé. Jamais silencieusement ignoré.

### Ne jamais toucher à Carvajal

Le module `l10n_co_edi` et sa configuration Carvajal pour la facturation électronique DIAN sont opérationnels en production. Toute modification nécessite un test complet sur staging.

### Les sources externes échouent gracieusement

DIAN MUISCA a des fenêtres de maintenance programmées. RUES peut retourner du HTML. Ces pannes ne bloquent jamais le pipeline. La pré-qualification calcule le score sur les données disponibles, retourne AMARILLO provisional, et planifie un retry J+1.

---

## 2. Règles de code

### Validation du NIT

Le NIT colombien a un dígito de verificación (DV) calculable algorithmiquement. **Toujours valider le DV avant d'appeler Odoo.** Un NIT avec un mauvais DV est une erreur d'extraction, pas un NIT valide.

```python
# CORRECT
nit_result = validate_nit(extracted_nit)
if not nit_result.is_valid:
    raise ValidationError(f"NIT invalide: {nit_result.error}")

# INTERDIT
odoo_client.upsert_partner(extracted_nit)  # sans validation préalable
```

### Idempotence obligatoire

Toute opération vers Odoo doit pouvoir être rejouée sans effet de bord. Si un document est retraité (ex : `make docs-reset`), le résultat doit être identique.

```python
# CORRECT : upsert sur vat
existing = odoo._call("res.partner", "search_read", [[["vat", "=", nit]]], {"fields": ["id"], "limit": 1})
if existing:
    odoo._call("res.partner", "write", [[existing[0]["id"]], vals])
else:
    odoo._call("res.partner", "create", [vals])

# INTERDIT
odoo._call("res.partner", "create", [vals])  # doublon si rejoué
```

### Extraction persona natural vs jurídica

Le champ 24 du RUT indique le type de contribuyente. **Toujours router selon le champ 24** avant de tenter le champ 35 :

```
champ 24 contient "natural"  → champs 31-34 (apellidos + nombres)
champ 24 contient "jurídica" → champ 35 (Razón Social)
champ 24 absent              → champ 35, fallback 31-34
```

pdfplumber peut colapser les 4 colonnes 31-34 en une seule ligne de texte. **Toujours dédupliquer les parts** avec un `set` avant de les concaténer.

### Semáforo : ROJO seulement sur négatif confirmé

```python
# CORRECT
if dian_estado in ("Cancelado", "Suspendido"):
    semaforo = "rojo"
elif score >= 60:
    semaforo = "verde"
elif score >= 35 or fuentes_fallidas:
    semaforo = "amarillo"  # AMARILLO même si score < 35 quand sources sont down
else:
    semaforo = "rojo"

# INTERDIT
if score < 35:
    semaforo = "rojo"  # faux si les sources externes sont juste indisponibles
```

### RetryStore : lire l'env var en fallback

`RetryStore()` appelé sans argument lit `AUDIT_DB_DSN` depuis l'environnement. Ne jamais passer une chaîne vide explicitement :

```python
# CORRECT (runner.py)
self._retry_store = retry_store or RetryStore()  # lit os.getenv en interne

# CORRECT (script CLI)
store = RetryStore(dsn=os.getenv("AUDIT_DB_DSN", ""))
```

### Modèle de données Pydantic (champs Odoo vérifiés sur l'instance)

Les valeurs ci-dessous sont vérifiées sur l'instance réelle :

```python
class RUTExtraction(BaseModel):
    doc_id: str
    extraction_engine: ExtractionEngine    # 'pdfplumber'
    extraction_confidence: float           # [0.0, 1.0]
    vat: Optional[FieldExtraction]         # NIT sans DV
    name: Optional[FieldExtraction]        # Razón Social ou nom complet
    l10n_latam_identification_type_id: int = 4   # NIT = id 4 (ATTENTION: pas 31)
    l10n_co_edi_fiscal_regimen: Optional[FieldExtraction]
    # Valeurs réelles: '48'=IVA, '49'=No Aplica, '04'=INC, 'ZA'=IVA+INC
```

### Tags Odoo : utiliser l'existant

Les tags `Cliente`, `Proveedor`, `B2B` existent déjà. Seul `Import_Auto` a été créé par le pipeline (id=15). Ne pas créer de nouveaux tags en doublon.

### Logging structuré uniquement

Pas de `print()`, pas de f-strings dans les messages de log.

```python
# CORRECT
log.info("extraction_done", doc_id=doc_id, nit=nit, confidence=1.0)

# INTERDIT
print(f"Extraction OK pour {doc_id}")
log.info(f"Extraction OK pour {doc_id}")
```

### Texte utilisateur en espagnol

Tous les textes visibles dans Odoo (chatter, oportunidades CRM, messages d'erreur UI) sont en **espagnol**. La documentation technique reste en français.

---

## 3. Seuils et paramètres opérationnels

| Paramètre | Valeur | Raison |
|---|---|---|
| Seuil confiance extraction | `0.92` | En dessous, le taux d'erreur terrain est inacceptable |
| Tentatives retry Odoo | `3` | Au-delà, le problème est structurel |
| Backoff max | `10s` | Évite de saturer l'API Odoo |
| Seuil pré-qualification VERDE | `60` | Score basé sur signaux DIAN mesurés terrain |
| Seuil pré-qualification AMARILLO | `35` | En dessous = profil insuffisant (si sources confirmées) |
| Seuil capital RUES | `150 M COP` | Proxy de solvabilité pour Industrias Pico |
| Score Autorretenedor | `40 pts` | Implique RUT actif + revenus > 720 M COP/an (DIAN) |
| Timeout sources externes | `10s` | DIAN et RUES peuvent être lents |
| Retry pré-qualification | J+1 à la même heure | Cron quotidien recommandé à 08h00 |

---

## 4. Règles HITL (Human-In-The-Loop) — Sprint 2

### Quand un document part en HITL

- Confiance extraction sur un champ obligatoire `< 0.92`
- NIT avec DV invalide (l'humain corrige la valeur extraite)
- Champ obligatoire (`vat` ou `name`) absent

Dans Odoo Documents, le document reçoit le tag **"To Validate"** (id=2).

### Ce que l'opérateur peut faire

- Corriger la valeur d'un champ extrait
- Valider → remet le document dans le pipeline auto
- Rejeter → laisse sans tag validé avec note d'erreur
- Marquer "document illisible" → notification à l'expéditeur

### Ce que l'opérateur ne peut pas faire

- Modifier directement Odoo — toujours passer par le pipeline
- Bypasser la validation NIT — le DV est toujours recalculé après correction humaine

---

## 5. Pré-qualification — règles métier

### Score et semáforo

Le score de pré-qualification est intentionnellement conservateur quand les sources externes sont indisponibles. Un AMARILLO avec sources indisponibles ne signifie pas que le client est risqué — il signifie que les données sont insuffisantes pour confirmer VERDE.

### Autorretenedor (code 15) = proxy fort

La qualification Autorretenedor attribuée par la DIAN certifie : ingresos brutos > ~720 M COP/an + RUT actif + déclarations de retenciones à jour. Signal le plus fort disponible depuis le RUT seul.

### Sources externes défaillantes

| Log émis | Signification | Action |
|---|---|---|
| `dian_viewstate_not_found` | MUISCA redirige vers maintenance | Normal, temporaire. Score sans +20 DIAN, retry J+1 planifié |
| `rues_html_response` | RUES retourne du HTML (SPA React) | Backend legacy non disponible. Score sans +20 RUES, retry J+1 planifié |
| `dian_check_failed` | Erreur réseau ou parsing inattendu | Vérifier connectivité réseau |
| `rues_check_failed` | Exception lors de l'appel RUES | Vérifier connectivité réseau |

### Ne pas modifier le semáforo manuellement dans Odoo

L'oportunidad CRM créée par le pipeline est le point d'entrée pour la décision Hector. Si Hector veut modifier la décision, il le fait dans le CRM Odoo. Ne pas rétrospectivement corriger le score calculé — il doit refléter l'état au moment de l'import.

---

## 6. Conformité Ley 1581 (données personnelles colombiennes)

La Ley 1581 de 2012 encadre le traitement des données personnelles en Colombie.

| Obligation | Implémentation |
|---|---|
| Finalité déclarée | Traitement uniquement pour création/mise à jour contact client dans Odoo |
| Traçabilité | Audit log : `timestamp`, `odoo_action`, `doc_id` pour chaque opération |
| Droit d'accès | L'audit log permet de reconstituer l'historique complet d'un contact |
| Sécurité | Credentials en variables d'environnement uniquement — `.env` dans `.gitignore` |
| Conservation | Rétention illimitée (obligation fiscale colombienne) |

> **`pdfplumber` retenu** — aucune donnée ne quitte le périmètre, pas de DPA requis.

> **Facturation électronique :** Carvajal est l'OAH déjà contractualisé. Ne pas engager d'autre prestataire DIAN sans valider avec l'équipe.

---

## 7. Plan de déploiement

### Sprint 1 — Fondations ✅ TERMINÉ (2026-05-23)

- ✅ Connexion XML-RPC validée sur `industriaspico-industriaspico-main-14967325`
- ✅ Validateur NIT avec 15 tests (DV correct/incorrect, formats variés)
- ✅ Extraction pdfplumber — patterns basés sur numéros de champs DIAN
- ✅ Gate confiance (0.92) + Gate NIT (DV algorithmique) + Gate champs
- ✅ Upsert idempotent sur `vat` — champs CO réels vérifiés sur l'instance
- ✅ Tags `Cliente`/`Proveedor` + `B2B` + `Import_Auto` (id=15)
- ✅ Intelligence fiscale — profil CIIU + codes responsabilidad → chatter Odoo
- ✅ Pré-qualification — score 0–100 + semáforo → oportunidad CRM
- ✅ Audit log PostgreSQL (`pipeline_audit_log`)

### Sprint 1 — Extensions ✅ TERMINÉ (2026-06-03)

- ✅ Ingestion depuis Odoo Documents — workspace "RUTs Clientes" (id=196)
- ✅ Routing persona natural (champ 24) / jurídica (champ 35) avec fallback
- ✅ Déduplication nom persona natural (pdfplumber collapse colonnes 31-34)
- ✅ Correction faux ROJO — AMARILLO provisional quand sources externes down
- ✅ Retry différé J+1 (`prequal_retries` PostgreSQL + `make prequal-retry`)
- ✅ `make docs-reset` — réinitialisation tags + retraitement
- ✅ Audit log no-op si AUDIT_DB_DSN absent (graceful degradation)

**Test réel :** 16 documents traités (4 personas naturales + 12 jurídicas) — extraction correcte, retries planifiés, audit écrit.

---

### Sprint 2 — Queue + HITL (à venir)

- [ ] Queue Redis Streams (`documents.incoming`, `documents.hitl`, `documents.failed`)
- [ ] Worker d'extraction connecté à la queue
- [ ] Interface HITL FastAPI + HTMX (document côte à côte avec champs extraits)
- [ ] Alertes Slack sur DLQ
- [ ] Dashboard Metabase basique sur `pipeline_audit_log`

---

### Sprint 3 — Intégrations (à venir)

- [ ] Ingestion email (alias dédié `rut@...` → parsing MIME → queue)
- [ ] Observabilité complète : 4 dashboards Metabase + alertes Slack

---

## 8. Runbook d'exploitation

### Retraiter tous les documents du workspace

```bash
make docs-reset    # réinitialise les tags + relance l'ingestion
```

### Relancer les pré-qualifications en attente

```bash
make prequal-retry

# Via cron (recommandé)
# 0 8 * * * cd /chemin/projet && make prequal-retry >> logs/retry.log 2>&1
```

### Document bloqué (tag "To Validate")

1. Ouvrir Odoo Documents → workspace "RUTs Clientes"
2. Lire la note chatter sur le document (message d'erreur ou raison HITL)
3. **Score extraction bas** → vérifier si le PDF est un scan (pdfplumber ne fait pas d'OCR)
4. **NIT invalide** → correction manuelle requise (Sprint 2 : interface HITL)
5. **Champ manquant** → vérifier si le format du document a changé

### Doublon détecté dans Odoo

1. **Ne pas supprimer** — fusionner via Odoo : `res.partner` → Action → Fusionner
2. Vérifier dans l'audit log les deux créations (`nit_extracted`)

### Taux d'erreur extraction > 5%

1. Filtrer `needs_hitl = true` dans l'audit log
2. Analyser : nouveau type de document ? Qualité dégradée ? Changement format DIAN ?
3. Vérifier si le PDF est bien numérique (pas un scan)

---

## 9. Ce qu'il ne faut pas faire

| Interdit | Pourquoi |
|---|---|
| `l10n_latam_identification_type_id = 31` | La valeur réelle est **4** — 31 provoque une erreur Odoo |
| `l10n_co_edi_fiscal_regimen = 'common'` | Valeurs invalides — utiliser `'48'`, `'49'`, `'04'`, `'ZA'` |
| Créer des contacts sans passer par le pipeline | Casse l'audit trail, crée des doublons |
| Modifier les étapes du pipeline CRM | Bloque les opérations commerciales |
| Toucher à Carvajal / `l10n_co_edi` | La facturation DIAN est opérationnelle |
| Modifier `pipeline_audit_log` sans migration SQL | Casse les requêtes existantes |
| Stocker des credentials en dur dans le code | Variables d'environnement uniquement |
| Bloquer le pipeline sur une source externe défaillante | DIAN et RUES peuvent être indisponibles |
| ROJO sur score bas seul quand sources sont down | Faux négatif — utiliser AMARILLO provisional |
