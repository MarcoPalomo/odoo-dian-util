VENV := ../.venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.DEFAULT_GOAL := help

.PHONY: help install build open clean

help: ## Afficher cette aide
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ── Installation ──────────────────────────────────────────────────────────────

install: ## Installer PyInstaller dans le venv partagé
	$(PIP) install -q pyinstaller
	@echo "  PyInstaller prêt — $(shell $(VENV)/bin/pyinstaller --version)"

# ── Build ─────────────────────────────────────────────────────────────────────

build: install ## Construire RUT Pipeline.app
	$(VENV)/bin/pyinstaller --noconfirm RUTPipeline.spec
	@echo ""
	@echo "  ✅  App générée : dist/RUT Pipeline.app"
	@echo ""
	@echo "  Pour tester :"
	@echo "    open 'dist/RUT Pipeline.app'"
	@echo ""
	@echo "  Pour distribuer :"
	@echo "    make dmg   (crée un installeur DMG)"

open: ## Ouvrir l'app après build
	open 'dist/RUT Pipeline.app'

# ── DMG (optionnel) ───────────────────────────────────────────────────────────

dmg: build ## Créer un installeur DMG (nécessite create-dmg)
	@which create-dmg > /dev/null || (echo "  Installez create-dmg : brew install create-dmg" && exit 1)
	create-dmg \
		--volname "RUT Pipeline" \
		--window-pos 200 120 \
		--window-size 600 400 \
		--icon-size 100 \
		--icon "RUT Pipeline.app" 175 190 \
		--hide-extension "RUT Pipeline.app" \
		--app-drop-link 425 190 \
		"dist/RUT-Pipeline.dmg" \
		"dist/RUT Pipeline.app"
	@echo "  ✅  DMG : dist/RUT-Pipeline.dmg"

# ── Nettoyage ─────────────────────────────────────────────────────────────────

clean: ## Supprimer les artefacts de build
	rm -rf build/ dist/ __pycache__ *.pyc
	@echo "  Nettoyé."
