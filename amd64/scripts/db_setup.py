#!/usr/bin/env python3
"""
Crée la base pipeline_audit et applique le schéma.
Remplace createdb + psql — utilise uniquement psycopg2.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent.parent / ".env")

DSN = os.getenv("AUDIT_DB_DSN", "postgresql://postgres:postgres@localhost:5432/pipeline_audit")

# Extraire la base cible et construire le DSN sur "postgres" pour la créer
def _admin_dsn(dsn: str) -> tuple[str, str]:
    """Retourne (dsn_sur_postgres, nom_de_la_base)."""
    import re
    m = re.match(r"(postgresql://[^/]+/)(\w+)(.*)", dsn)
    if not m:
        raise ValueError(f"DSN non reconnu : {dsn}")
    return m.group(1) + "postgres" + m.group(3), m.group(2)

def main():
    admin_dsn, dbname = _admin_dsn(DSN)

    # 1. Créer la base si elle n'existe pas
    conn = psycopg2.connect(admin_dsn)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        if cur.fetchone():
            print(f"Base '{dbname}' existe déjà.")
        else:
            cur.execute(f'CREATE DATABASE "{dbname}"')
            print(f"Base '{dbname}' créée.")
    conn.close()

    # 2. Appliquer le schéma
    sql = (Path(__file__).parent.parent / "sql" / "create_audit_log.sql").read_text()
    conn2 = psycopg2.connect(DSN)
    with conn2.cursor() as cur:
        cur.execute(sql)
    conn2.commit()
    conn2.close()
    print("Schéma pipeline_audit_log appliqué.")

if __name__ == "__main__":
    main()
