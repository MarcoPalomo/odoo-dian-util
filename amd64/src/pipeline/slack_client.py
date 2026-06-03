"""Stub alertes Slack — DLQ uniquement. Silencieux si SLACK_WEBHOOK_URL absent."""
from __future__ import annotations

import os

import requests
import structlog

log = structlog.get_logger()


def notify_dlq(
    doc_id: str,
    s3_path: str,
    error_type: str,
    error_message: str,
    source: str,
) -> None:
    url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        log.warning("slack_dlq_no_webhook", doc_id=doc_id)
        return
    payload = {
        "text": f"\U0001f6a8 *DLQ* `{doc_id}` (`{source}`) — `{error_type}`: {error_message}"
    }
    try:
        requests.post(url, json=payload, timeout=5)
        log.info("slack_dlq_sent", doc_id=doc_id)
    except Exception as exc:
        log.warning("slack_notify_failed", error=str(exc))
