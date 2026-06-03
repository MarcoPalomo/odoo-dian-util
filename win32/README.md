# RUT Pipeline — Windows (planifié)

Portage Windows du pipeline RUT → Odoo pour Industrias Pico.

← [Retour au README principal](../README.md)

---

## Statut

**Non implémenté.** Ce répertoire est un placeholder pour la future version Windows.

---

## Stack technique envisagée

| Composant | Librairie | Rôle |
|---|---|---|
| Extraction PDF | [PdfPig](https://uglytoad.github.io/PdfPig/) | Équivalent pdfplumber |
| Odoo XML-RPC | [CookComputing.XmlRpcV2](http://www.cookcomputing.com/xmlrpcnet/index.html) | Upsert contacts |
| PostgreSQL | [Npgsql](https://www.npgsql.org/) | Audit log + retries |
| Logging structuré | [Serilog](https://serilog.net/) | Équivalent structlog |
| Interface graphique | WinForms ou WPF | Équivalent tkinter launcher |
| Configuration | `%APPDATA%\RUTPipeline\.env` | Équivalent `~/Library/…/.env` |
| Distribution | Installeur NSIS ou WiX | Équivalent DMG macOS |

---

## Comportement attendu

Identique à la version macOS :
- Interface graphique avec zone de log en temps réel
- Sélecteur de fichier PDF local
- Bouton "Ingérer depuis Odoo Documents"
- Lecture de la config depuis `%APPDATA%\RUTPipeline\.env`

---

## Pour contribuer

Référence : [`darwin/launcher.py`](../darwin/launcher.py) — l'interface tkinter macOS sert de spécification fonctionnelle pour le portage WinForms/WPF.

La logique métier (extraction, NIT, pré-qualification, upsert Odoo) doit être portée fidèlement depuis [`amd64/src/pipeline/`](../amd64/src/pipeline/).
