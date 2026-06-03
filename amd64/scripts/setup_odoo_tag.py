#!/usr/bin/env python3
"""
Script one-shot — crée le tag Import_Auto dans Odoo s'il n'existe pas.
À exécuter une seule fois en Sprint 1.
Usage: python scripts/setup_odoo_tag.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

import structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

from pipeline.odoo_client import OdooClient

log = structlog.get_logger()

TAGS_TO_ENSURE = ["Import_Auto"]


def main():
    client = OdooClient()
    for tag_name in TAGS_TO_ENSURE:
        tag_id = client.get_or_create_tag(tag_name)
        log.info("tag_ready", name=tag_name, id=tag_id)
    print("\nSetup Odoo terminé.")


if __name__ == "__main__":
    main()
