VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.DEFAULT_GOAL := help

.PHONY: help install test lint \
        minio-up minio-down \
        postgres-up postgres-down \
        redis-up redis-down \
        infra-up infra-down \
        db-setup odoo-setup \
        dry-run run \
        docs-ingest docs-watch docs-dry-run docs-reset \
        prequal-retry

help: ## Afficher cette aide
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Environnement ─────────────────────────────────────────────────────────────

install: $(VENV)/bin/activate ## Créer le venv et installer les dépendances

$(VENV)/bin/activate: pyproject.toml
	python3 -m venv $(VENV)
	$(PIP) install -q -e ".[dev]"
	@touch $(VENV)/bin/activate

# ── Qualité ───────────────────────────────────────────────────────────────────

test: install ## Lancer tous les tests
	$(VENV)/bin/pytest tests/ -v

lint: install ## Vérifier le style (ruff)
	$(VENV)/bin/ruff check src/ scripts/

# ── Infra locale (Docker) ─────────────────────────────────────────────────────

minio-up: ## Démarrer MinIO
	docker run -d \
		--name minio \
		-p 9000:9000 -p 9001:9001 \
		-e MINIO_ROOT_USER=minioadmin \
		-e MINIO_ROOT_PASSWORD=minioadmin \
		-v minio_data:/data \
		quay.io/minio/minio server /data --console-address ":9001" \
	|| docker start minio
	@echo "  Console MinIO : http://localhost:9001 (minioadmin / minioadmin)"

minio-down: ## Arrêter MinIO
	docker stop minio

postgres-up: ## Démarrer PostgreSQL audit
	docker run -d \
		--name pipeline-postgres \
		-p 5432:5432 \
		-e POSTGRES_USER=pipeline \
		-e POSTGRES_PASSWORD=pipeline \
		-e POSTGRES_DB=postgres \
		-v pipeline_pg_data:/var/lib/postgresql/data \
		postgres:16-alpine \
	|| docker start pipeline-postgres
	@echo "  PostgreSQL prêt sur localhost:5432 (pipeline / pipeline)"

postgres-down: ## Arrêter PostgreSQL audit
	docker stop pipeline-postgres

redis-up: ## Démarrer Redis
	docker run -d --name pipeline-redis -p 6379:6379 redis:7-alpine \
	|| docker start pipeline-redis
	@echo "  Redis prêt sur localhost:6379"

redis-down: ## Arrêter Redis
	docker stop pipeline-redis

infra-up: postgres-up redis-up minio-up ## Démarrer toute l'infra locale (postgres + redis + minio)
	@echo ""
	@echo "  Infra démarrée. Lance ensuite : make db-setup"

infra-down: postgres-down redis-down minio-down ## Arrêter toute l'infra locale

# ── Setup (one-shot) ──────────────────────────────────────────────────────────

.stamps/db-setup: scripts/db_setup.py sql/create_audit_log.sql
	@mkdir -p .stamps
	$(MAKE) postgres-up
	@echo "Attente démarrage PostgreSQL..."
	@sleep 3
	$(PY) scripts/db_setup.py
	@touch .stamps/db-setup

db-setup: install .stamps/db-setup ## Créer le schéma d'audit (skip si déjà fait)

odoo-setup: install ## Créer le tag Import_Auto + workspace RUTs Clientes dans Odoo
	$(PY) scripts/setup_odoo_tag.py

# ── Pipeline CLI ──────────────────────────────────────────────────────────────

dry-run: install ## Tester l'extraction sur un PDF sans écrire (usage: make dry-run PDF=rut.pdf)
ifndef PDF
	$(error Spécifie le fichier : make dry-run PDF=chemin/vers/rut.pdf)
endif
	$(PY) scripts/process_rut.py "$(PDF)" --dry-run

run: install ## Traiter un RUT en production (usage: make run PDF=rut.pdf)
ifndef PDF
	$(error Spécifie le fichier : make run PDF=chemin/vers/rut.pdf)
endif
	$(PY) scripts/process_rut.py "$(PDF)"

# ── Ingestion depuis Odoo Documents ──────────────────────────────────────────

docs-ingest: install ## Traiter les PDFs en attente dans le workspace "RUTs Clientes"
	$(PY) scripts/ingest_from_documents.py

docs-watch: install ## Surveiller le workspace "RUTs Clientes" en continu (poll 30s)
	$(PY) scripts/ingest_from_documents.py --watch

docs-dry-run: install ## Tester l'ingestion Documents sans écrire dans Odoo
	$(PY) scripts/ingest_from_documents.py --dry-run

docs-reset: install ## Réinitialiser les tags du workspace puis retraiter
	$(PY) scripts/ingest_from_documents.py --reset
	$(PY) scripts/ingest_from_documents.py

# ── Retry pré-qualification ───────────────────────────────────────────────────

prequal-retry: install ## Relancer les pré-qualifications DIAN/RUES en attente
	$(PY) scripts/retry_prequalification.py

# Pour planifier quotidiennement à la même heure (ex: 08h00) :
#   0 8 * * * cd /chemin/projet && make prequal-retry >> logs/retry.log 2>&1

