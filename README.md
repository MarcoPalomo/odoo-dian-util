# RUT Pipeline — Industrias Pico

Automatisation d'import des documents RUT (DIAN, Colombie) vers Odoo 17 Enterprise.
Instance cible : `industriaspico-industriaspico.odoo.com`

---

## Plateformes

| Répertoire | Plateforme | Statut | Interface |
|---|---|---|---|
| [`amd64/`](amd64/README.md) | Linux x86\_64 | Production | CLI + Makefile |
| [`darwin/`](darwin/README.md) | macOS 12+ | Disponible | Application .app (tkinter) |
| [`win32/`](win32/README.md) | Windows 10/11 | Planifié | À définir (C#/.NET) |

---

## Structure du dépôt

```
odoo-ml-ai/
├── amd64/                  # Version Linux complète (production)
│   ├── src/
│   │   ├── pipeline/       # Cœur du pipeline (extraction, upsert, prequal…)
│   │   └── hitl/           # Interface révision manuelle (FastAPI — Sprint 2)
│   ├── scripts/            # CLI : process_rut, ingest_from_documents, retry…
│   ├── tests/              # 15 tests unitaires (NIT validator, gates)
│   ├── sql/                # Schéma PostgreSQL audit_log + prequal_retries
│   ├── Makefile            # Cible principale d'exploitation
│   └── README.md
│
├── darwin/                 # Packaging macOS (PyInstaller .app)
│   ├── launcher.py         # GUI tkinter + redirection stdout → zone de log
│   ├── RUTPipeline.spec    # Spec PyInstaller
│   ├── Makefile            # make build / make dmg
│   └── README.md
│
└── win32/                  # Futur portage Windows (C#/.NET)
    └── README.md
```

---

## Architecture du pipeline

Le cœur du traitement (`src/pipeline/`) est partagé entre les plateformes.
Chaque plateforme fournit son propre lanceur.

```
PDF (fichier local ou Odoo Documents)
 │
 ├─ [Linux]   make docs-ingest / make run
 ├─ [macOS]   RUT Pipeline.app (GUI tkinter)
 └─ [Windows] À venir (C#/.NET → XML-RPC)
             │
             ▼
[Extraction pdfplumber]
  Champ 24 → persona natural (31–34) ou jurídica (35)
  NIT + DV, régimen, CIIU, responsabilidades
             │
             ▼
[Gates]  confiance ≥ 0.92  |  DV valide  |  champs obligatoires
             │
             ▼
[Upsert Odoo XML-RPC]   search(vat) → create ou write (idempotent)
             │
             ▼
[Pré-qualification]   semáforo VERDE/AMARILLO/ROJO → oportunidad CRM
  Sources : RUT interne (60 pts) + DIAN (20 pts) + RUES (20 pts)
  DIAN/RUES indisponibles → AMARILLO + retry J+1
             │
             ▼
[Audit log PostgreSQL]   toujours écrit (succès, HITL, erreur)
```

---

## Flux Odoo Documents (mode principal Linux)

1. Déposer le PDF RUT dans le workspace **"RUTs Clientes"** (Documents Odoo)
2. Lancer `make docs-ingest` (ou `make docs-watch` pour la surveillance continue)
3. Le document est tagué **Validated** — le contact Odoo est créé ou mis à jour

---

## Documentation technique

| Fichier | Contenu |
|---|---|
| [`amd64/ARCHITECTURE.md`](amd64/ARCHITECTURE.md) | Diagrammes détaillés, modules, invariants |
| [`amd64/GUIDELINE.md`](amd64/GUIDELINE.md) | Règles de développement, runbook, anti-patterns |

---

## Sécurité

- `.env` dans `.gitignore` — les credentials ne sont jamais committés
- Ne jamais toucher `l10n_co_edi` (facturation DIAN opérationnelle en production)
- Tout texte visible dans Odoo (chatter, CRM, messages) en **español**
