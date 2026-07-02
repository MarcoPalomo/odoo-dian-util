# RUT Pipeline — Windows 10/11

Portage Windows du pipeline RUT → Odoo pour Industrias Pico.
Interface graphique tkinter identique à la version macOS.

← [Retour au README principal](../README.md)

---

## Prérequis

| Logiciel | Version | Lien |
|---|---|---|
| Python | 3.11+ | https://python.org (cocher "Add to PATH") |
| Visual C++ Redistributable | 2015–2022 | Inclus dans Windows 11, sinon https://aka.ms/vs/17/release/vc_redist.x64.exe |

---

## Installation et build

```powershell
# Depuis le dossier win32\
.\build.ps1
```

Le script :
1. Crée un venv Python partagé à `..\.venv`
2. Installe les dépendances (`pyproject.toml`)
3. Génère `icon.ico`
4. Produit `dist\RUT Pipeline\RUT Pipeline.exe`
5. Crée un raccourci sur le Bureau

---

## Configuration

Avant le premier lancement, créez le fichier de configuration :

```
%APPDATA%\RUTPipeline\.env
```

Copiez `.env.example` comme modèle et renseignez vos credentials Odoo.
L'application affiche un avertissement au démarrage si ce fichier est absent.

---

## Autres commandes

```powershell
.\build.ps1 run     # Lancer en mode dev (sans build)
.\build.ps1 clean   # Supprimer build/ dist/ icon.ico
```

---

## Distribution

Pour distribuer l'application, copiez le dossier `dist\RUT Pipeline\` entier.
L'exécutable `RUT Pipeline.exe` est autonome (pas besoin de Python installé).

Optionnel : créer un installeur avec [NSIS](https://nsis.sourceforge.io/) ou [Inno Setup](https://jrsoftware.org/isinfo.php).

---

## Interface

| Bouton | Action |
|---|---|
| **Traiter un PDF…** | Ouvre un sélecteur de fichier, traite le RUT PDF localement |
| **Ingérer depuis Odoo Documents** | Récupère et traite tous les PDFs du workspace "RUTs Clientes" |

La zone **Journal** affiche la sortie du pipeline en temps réel.

---

## Référence

- Code pipeline : [`amd64/src/pipeline/`](../amd64/src/pipeline/)
- Équivalent macOS : [`darwin/launcher.py`](../darwin/launcher.py)
