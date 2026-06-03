"""
Client MinIO/S3 — archivage immuable des documents bruts.
Principe : archiver avant de traiter. Jamais de traitement sans archivage préalable.
"""
from __future__ import annotations

import hashlib
import io
import os
from datetime import datetime
from pathlib import Path

import structlog
from minio import Minio
from minio.error import S3Error
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "rut-documents")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"


class StorageClient:
    def __init__(self):
        self._client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
        self._bucket = MINIO_BUCKET
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
            log.info("bucket_created", bucket=self._bucket)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def archive(
        self,
        doc_id: str,
        file_path: Path,
        source: str,
        content_type: str = "application/pdf",
    ) -> str:
        """
        Archive un document dans MinIO et retourne le chemin S3.
        Le chemin est déterministe : {year}/{month}/{doc_id}/{filename}.
        """
        now = datetime.utcnow()
        object_name = f"{now.year}/{now.month:02d}/{doc_id}/{file_path.name}"

        data = file_path.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        size = len(data)

        metadata = {
            "x-amz-meta-doc-id": doc_id,
            "x-amz-meta-source": source,
            "x-amz-meta-sha256": sha256,
            "x-amz-meta-received-at": now.isoformat(),
        }

        self._client.put_object(
            self._bucket,
            object_name,
            io.BytesIO(data),
            length=size,
            content_type=content_type,
            metadata=metadata,
        )

        s3_path = f"s3://{self._bucket}/{object_name}"
        log.info(
            "document_archived",
            doc_id=doc_id,
            s3_path=s3_path,
            sha256=sha256,
            size_bytes=size,
            source=source,
        )
        return s3_path

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def download(self, s3_path: str, local_path: Path) -> None:
        """Télécharge un objet depuis MinIO vers un chemin local."""
        if s3_path.startswith("dry-run://"):
            raise ValueError(f"Cannot download dry-run path: {s3_path}")
        object_name = s3_path.split(f"s3://{self._bucket}/", 1)[-1]
        self._client.fget_object(self._bucket, object_name, str(local_path))
        log.info("document_downloaded", s3_path=s3_path, local_path=str(local_path))

    def get_url(self, s3_path: str, expires_seconds: int = 3600) -> str:
        """Génère une URL présignée temporaire pour accès en lecture (HITL UI)."""
        # Extraire object_name depuis "s3://bucket/path"
        object_name = s3_path.split(f"s3://{self._bucket}/", 1)[-1]
        from datetime import timedelta
        url = self._client.presigned_get_object(
            self._bucket, object_name, expires=timedelta(seconds=expires_seconds)
        )
        return url
