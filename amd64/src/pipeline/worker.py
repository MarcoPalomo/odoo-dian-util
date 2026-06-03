"""
Worker Redis Streams — consomme documents:incoming, orchestre le pipeline.
Poison-pill guard : si delivery_count >= MAX_RETRIES → DLQ forcé.
"""
from __future__ import annotations

import shutil
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

from pipeline.models import DocumentSource
from pipeline.queue_client import QueueClient
from pipeline.runner import Pipeline
from pipeline.slack_client import notify_dlq
from pipeline.storage_client import StorageClient

log = structlog.get_logger()

MAX_RETRIES = 3


class Worker:
    def __init__(
        self,
        queue: QueueClient,
        pipeline: Pipeline,
        storage: StorageClient,
    ):
        self._queue = queue
        self._pipeline = pipeline
        self._storage = storage
        self._consumer = f"worker-{socket.gethostname()}"

    def run(self, poll_interval_ms: int = 5000) -> None:
        log.info("worker_started", consumer=self._consumer)
        while True:
            messages = self._queue.read_incoming(
                self._consumer, count=1, block_ms=poll_interval_ms
            )
            for msg_id, fields in messages:
                self._process_message(msg_id, fields)

    def _process_message(self, msg_id: str, fields: dict[str, str]) -> None:
        doc_id = fields.get("doc_id", "unknown")
        s3_path = fields.get("s3_path", "")
        source_str = fields.get("source", DocumentSource.UPLOAD.value)
        is_cliente = fields.get("is_cliente", "true") == "true"

        log.info("worker_processing", doc_id=doc_id, s3_path=s3_path)
        tmpdir = tempfile.mkdtemp(prefix="pipeline_")
        try:
            pdf_path = Path(tmpdir) / f"{doc_id}.pdf"
            self._storage.download(s3_path, pdf_path)

            try:
                source = DocumentSource(source_str)
            except ValueError:
                source = DocumentSource.UPLOAD

            result = self._pipeline.process(
                pdf_path=pdf_path,
                source=source,
                is_cliente=is_cliente,
                doc_id=doc_id,
                s3_path=s3_path,
            )

            if result.needs_hitl and result.extraction is not None:
                self._route_to_hitl(doc_id, s3_path, source_str, is_cliente, result)
            elif result.error:
                self._route_to_failed(doc_id, s3_path, source_str, "pipeline_error", result.error)

            self._queue.ack(QueueClient.STREAM_INCOMING, QueueClient.GROUP_WORKERS, msg_id)
            log.info("worker_done", doc_id=doc_id)

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            log.exception("worker_unexpected_error", doc_id=doc_id, error=error_msg)
            if self._delivery_count(msg_id) >= MAX_RETRIES:
                log.error("worker_poison_pill", doc_id=doc_id, msg_id=msg_id)
                self._queue.ack(QueueClient.STREAM_INCOMING, QueueClient.GROUP_WORKERS, msg_id)
                self._route_to_failed(doc_id, s3_path, source_str, "poison_pill", error_msg)
            # sinon : ne pas acker, Redis relivrera

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _route_to_hitl(
        self,
        doc_id: str,
        s3_path: str,
        source: str,
        is_cliente: bool,
        result,
    ) -> None:
        payload = {
            "doc_id": doc_id,
            "s3_path": s3_path,
            "source": source,
            "is_cliente": str(is_cliente).lower(),
            "extraction_json": result.extraction.model_dump_json(),
            "hitl_reason": "low_confidence",
            "submitted_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        self._queue.publish(QueueClient.STREAM_HITL, payload)
        log.info("worker_routed_hitl", doc_id=doc_id)

    def _route_to_failed(
        self,
        doc_id: str,
        s3_path: str,
        source: str,
        error_type: str,
        error_message: str,
    ) -> None:
        self._queue.publish_failed(doc_id, s3_path, source, error_type, error_message)
        notify_dlq(doc_id, s3_path, error_type, error_message, source)

    def _delivery_count(self, msg_id: str) -> int:
        pending = self._queue._r.xpending_range(
            QueueClient.STREAM_INCOMING,
            QueueClient.GROUP_WORKERS,
            min=msg_id,
            max=msg_id,
            count=1,
        )
        if pending:
            return pending[0].get("times_delivered", 0)
        return 0
