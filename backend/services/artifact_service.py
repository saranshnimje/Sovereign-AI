"""
Artifact service — manages agent-generated files with persistent storage.

On Render, local disk is ephemeral. Artifacts are stored in the data directory
and tracked in the database for persistence across deployments.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import shutil
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.artifact import Artifact
from models.base import generate_uuid
from services.audit_service import AuditService

logger = logging.getLogger(__name__)


class ArtifactService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()

    def _get_artifact_dir(self, user_id: str) -> str:
        """Get the artifact storage directory for a user."""
        base = os.path.join(self.settings.data_dir, "artifacts", user_id)
        os.makedirs(base, exist_ok=True)
        return base

    async def create_artifact(
        self,
        user_id: str,
        filename: str,
        content: bytes | str,
        conversation_id: str | None = None,
        run_id: str | None = None,
        mime_type: str | None = None,
    ) -> Artifact:
        """Create a new artifact from content."""
        if isinstance(content, str):
            content = content.encode("utf-8")

        # Compute checksum
        checksum = hashlib.sha256(content).hexdigest()

        # Determine MIME type
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(filename)
            mime_type = mime_type or "application/octet-stream"

        # Generate storage path
        artifact_id = generate_uuid()
        ext = Path(filename).suffix or ".bin"
        storage_filename = f"{artifact_id}{ext}"
        user_dir = self._get_artifact_dir(user_id)
        storage_path = os.path.join(user_dir, storage_filename)
        relative_path = os.path.join(user_id, storage_filename)

        # Write to disk
        with open(storage_path, "wb") as f:
            f.write(content)

        # Create DB record
        artifact = Artifact(
            id=artifact_id,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            filename=filename,
            relative_path=relative_path,
            mime_type=mime_type,
            size_bytes=len(content),
            storage_key=storage_filename,
            checksum=checksum,
        )
        self.db.add(artifact)
        await self.db.flush()

        # Audit log
        audit = AuditService(self.db)
        await audit.log(
            "artifact", "artifact.created", "success",
            user_id=user_id,
            resource_type="artifact", resource_id=artifact_id,
            metadata={"filename": filename, "size_bytes": len(content)},
        )

        return artifact

    async def get_artifact(self, artifact_id: str, user_id: str) -> Artifact:
        """Get an artifact by ID with ownership check."""
        result = await self.db.execute(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.user_id == user_id,
            )
        )
        artifact = result.scalar_one_or_none()
        if not artifact:
            raise HTTPException(404, "Artifact not found")
        return artifact

    async def list_artifacts(
        self,
        user_id: str,
        conversation_id: str | None = None,
        run_id: str | None = None,
    ) -> list[Artifact]:
        """List artifacts for a user, optionally filtered by conversation or run."""
        query = select(Artifact).where(Artifact.user_id == user_id)
        if conversation_id:
            query = query.where(Artifact.conversation_id == conversation_id)
        if run_id:
            query = query.where(Artifact.run_id == run_id)
        query = query.order_by(Artifact.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def delete_artifact(self, artifact_id: str, user_id: str) -> None:
        """Delete an artifact and its file from disk."""
        artifact = await self.get_artifact(artifact_id, user_id)

        # Delete from disk
        user_dir = self._get_artifact_dir(user_id)
        storage_path = os.path.join(user_dir, artifact.storage_key)
        try:
            if os.path.exists(storage_path):
                os.remove(storage_path)
        except Exception as exc:
            logger.warning("Could not delete artifact file %s: %s", storage_path, exc)

        # Delete from DB
        await self.db.delete(artifact)
        await self.db.flush()

        audit = AuditService(self.db)
        await audit.log(
            "artifact", "artifact.deleted", "success",
            user_id=user_id,
            resource_type="artifact", resource_id=artifact_id,
        )

    def get_artifact_path(self, artifact: Artifact) -> str | None:
        """Get the absolute path to an artifact file. Returns None if not found."""
        user_dir = self._get_artifact_dir(artifact.user_id)
        path = os.path.join(user_dir, artifact.storage_key)
        if os.path.exists(path):
            return path
        return None
