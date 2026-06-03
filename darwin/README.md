# RUT Pipeline — macOS

Application macOS autonome pour importer les RUT DIAN dans Odoo 17 Enterprise.
Interface graphique (tkinter) construite avec PyInstaller — aucune installation Python requise pour l'utilisateur final.

← [Retour au README principal](../README.md)

---

## Prérequis (pour builder l'app)

| Outil | Version min | Usage |
|---|---|---|
| Python | 3.11 | Runtime + build |
| tkinter | inclus avec Python | Interface graphique |
| macOS | 12 (Monterey) | Cible de déploiement |

> tkinter est inclus dans les builds Python officiels (python.org). Si tu utilises Homebrew : `brew install python-tk@3.11`.

---

## Structure du répertoire

```
darwin/
├── launcher.py         # Point d'entrée GUI (tkinter)
├── RUTPipeline.spec    # Spec PyInstaller
├── Makefile            # make build / make open / make dmg / make clean
├── pyproject.toml      # Dépendances (référence ../src/pipeline)
└── .env.example        # Template de configuration
```

Le code du pipeline (`../src/pipeline/`) et les scripts (`../scripts/`) sont **partagés** avec la version Linux — darwin/ ne contient que le lanceur et le packaging.

---

## Configuration

L'application lit sa configuration depuis :

```
~/Library/Application Support/RUTPipeline/.env
```

### Créer le fichier de configuration

```bash
mkdir -p ~/Library/Application\ Support/RUTPipeline
cp .env.example ~/Library/Application\ Support/RUTPipeline/.env
```

Puis éditer `~/.../RUTPipeline/.env` :

```env
ODOO_URL=https://industriaspico-industriaspico.odoo.com
ODOO_DB=industriaspico-industriaspico-main-14967325
ODOO_USER=ton_user@industriaspico.com
ODOO_PASSWORD=ton_mot_de_passe

# PostgreSQL — audit log + retries (optionnel)
AUDIT_DB_DSN=postgresql://pipeline:pipeline@localhost:5432/pipeline_audit

# MinIO / S3 — archivage raw (optionnel)
# MINIO_ENDPOINT=localhost:9000
# MINIO_ACCESS_KEY=minioadmin
# MINIO_SECRET_KEY=minioadmin
# MINIO_BUCKET=rut-documents
# MINIO_SECURE=false

CONFIDENCE_THRESHOLD=0.92
```

> Si `AUDIT_DB_DSN` est absent : l'audit log et les retries de pré-qualification sont désactivés (l'app fonctionne quand même).
> Si `MINIO_ENDPOINT` est absent : l'archivage S3 est désactivé.

---

## Build

Depuis le répertoire `darwin/` :

```bash
# Installer PyInstaller (une seule fois)
make install

# Construire RUT Pipeline.app
make build
# → dist/RUT Pipeline.app

# Ouvrir immédiatement l'app pour tester
make open
```

---

## Distribution — DMG

Pour créer un installeur DMG distribuable :

```bash
# Prérequis : brew install create-dmg
make dmg
# → dist/RUT-Pipeline.dmg
```

L'utilisateur final reçoit le DMG, le monte, glisse l'app dans Applications — aucune installation Python requise.

---

## Utilisation de l'application

Au premier lancement, si le fichier `.env` est absent, l'app affiche un avertissement avec les instructions de configuration.

**Actions disponibles dans l'interface :**

| Bouton | Effet |
|---|---|
| Traiter un PDF… | Ouvre un sélecteur de fichier — traite un RUT PDF local via le pipeline complet |
| Ingérer depuis Odoo Documents | Traite tous les PDFs en attente dans le workspace "RUTs Clientes" |

Les logs du pipeline s'affichent en temps réel dans la zone "Journal".

---

## Architecture interne

```
launcher.py
 │
 ├─ _QueueStream          stdout/stderr → queue.Queue (thread-safe)
 ├─ _poll_logs()          tkinter after(100ms) → zone de log
 ├─ _check_config()       charge ~/Library/.../RUTPipeline/.env
 ├─ _pick_pdf()           file dialog → _process_pdf() dans un thread
 └─ _ingest_docs()        _process_docs() dans un thread
         │
         ▼
   pipeline.runner.Pipeline   (partagé avec la version Linux)
```

---

## Makefile — Cibles

```
make help       Afficher cette aide
make install    Installer PyInstaller dans le venv partagé (../.venv)
make build      Construire RUT Pipeline.app (inclut install)
make open       Ouvrir l'app après build
make dmg        Créer un installeur DMG distribuable (nécessite create-dmg)
make clean      Supprimer build/ dist/ __pycache__
```

---

## Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| Avertissement `.env` au lancement | Fichier de config absent | Créer `~/Library/Application Support/RUTPipeline/.env` |
| `⚠ MINIO_ENDPOINT absent` | Normal si S3 non configuré | Ignorer — archivage désactivé |
| `ModuleNotFoundError` au build | Dépendance manquante dans hiddenimports | Ajouter dans `RUTPipeline.spec` |
| L'app ne s'ouvre pas sur macOS | Quarantaine Gatekeeper | `xattr -rd com.apple.quarantine "dist/RUT Pipeline.app"` |
| tkinter absent | Python installé sans tk | `brew install python-tk@3.11` |
