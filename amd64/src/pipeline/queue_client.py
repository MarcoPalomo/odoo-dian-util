"""
Client Redis Streams — abstraction queue pour le pipeline Sprint 2.
Trois streams : incoming (worker), hitl (opérateurs), failed (DLQ).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import structlog
from redis import Redis
from redis.exceptions import ResponseError

log = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class QueueClient:
    STREAM_INCOMING = "documents:incoming"
    STREAM_HITL = "documents:hitl"
    STREAM_FAILED = "documents:failed"
    GROUP_WORKERS = "pipeline-workers"
    GROUP_HITL = "hitl-operators"

    def __init__(self, redis_url: str = REDIS_URL):
        self._r: Redis = Redis.from_url(redis_url, decode_responses=True)
        self._ensure_groups()

    def _ensure_groups(self) -> None:
        pairs = [
            (self.STREAM_INCOMING, self.GROUP_WORKERS),
            (self.STREAM_HITL, self.GROUP_HITL),
        ]
        for stream, group in pairs:
            try:
                self._r.xgroup_create(stream, group, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    def publish(self, stream: str, payload: dict[str, str]) -> str:
        msg_id: str = self._r.xadd(stream, payload)
        log.info("queue_published", stream=stream, msg_id=msg_id)
        return msg_id

    def read_incoming(
        self,
        consumer_name: str,
        count: int = 1,
        block_ms: int = 5000,
    ) -> list[tuple[str, dict[str, str]]]:
        result = self._r.xreadgroup(
            self.GROUP_WORKERS,
            consumer_name,
            {self.STREAM_INCOMING: ">"},
            count=count,
            block=block_ms,
        )
        if not result:
            return []
        # result = [(stream_name, [(msg_id, fields), ...])]
        return result[0][1]

    def read_hitl(
        self,
        count: int = 50,
    ) -> list[tuple[str, dict[str, str]]]:
        """XRANGE non-consommant — pour affichage liste HITL uniquement."""
        return self._r.xrange(self.STREAM_HITL, count=count)

    def find_hitl_message(
        self, doc_id: str
    ) -> Optional[tuple[str, dict[str, str]]]:
        messages = self._r.xrange(self.STREAM_HITL)
        for msg_id, fields in messages:
            if fields.get("doc_id") == doc_id:
                return msg_id, fields
        return None

    def ack(self, stream: str, group: str, msg_id: str) -> None:
        self._r.xack(stream, group, msg_id)
        log.info("queue_acked", stream=stream, group=group, msg_id=msg_id)

    def publish_failed(
        self,
        doc_id: str,
        s3_path: str,
        source: str,
        error_type: str,
        error_message: str,
    ) -> str:
        payload = {
            "doc_id": doc_id,
            "s3_path": s3_path,
            "source": source,
            "error_type": error_type,
            "error_message": error_message,
            "failed_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        return self.publish(self.STREAM_FAILED, payload)

    def pending_hitl_count(self) -> int:
        return self._r.xlen(self.STREAM_HITL)

    def close(self) -> None:
        self._r.close()
