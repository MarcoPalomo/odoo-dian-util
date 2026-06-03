#!/usr/bin/env python3
"""Point d'entrée CLI pour le worker Redis Streams."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import click
from dotenv import load_dotenv

load_dotenv()

import structlog

from pipeline.audit_log import AuditLog
from pipeline.odoo_client import OdooClient
from pipeline.queue_client import QueueClient
from pipeline.runner import Pipeline
from pipeline.storage_client import StorageClient
from pipeline.worker import Worker

log = structlog.get_logger()


@click.command()
@click.option("--poll-ms", default=5000, show_default=True, help="Délai de polling en ms.")
@click.option("--dry-run", is_flag=True, help="Pipeline en mode dry-run (pas d'écriture Odoo).")
def main(poll_ms: int, dry_run: bool) -> None:
    """Worker qui consomme documents:incoming et orchestre le pipeline."""
    storage = StorageClient()
    odoo = OdooClient()
    audit = AuditLog()
    pipeline = Pipeline(storage=storage, odoo=odoo, audit=audit, dry_run=dry_run)
    queue = QueueClient()

    worker = Worker(queue=queue, pipeline=pipeline, storage=storage)
    try:
        worker.run(poll_interval_ms=poll_ms)
    except KeyboardInterrupt:
        log.info("worker_stopped")
    finally:
        queue.close()
        audit.close()


if __name__ == "__main__":
    main()
