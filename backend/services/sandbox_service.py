"""
Sandbox Service — Docker-based isolated Python execution.

Security profile (NON-NEGOTIABLE):
  - Fresh container per execution (no reuse)
  - Non-root user (UID 1000)
  - cap_drop = ["ALL"]
  - network_mode = "none"
  - read_only root filesystem
  - writable workspace volume (temp dir, cleaned after run)
  - pids_limit = 50
  - memory limit (configurable, default 256 MB)
  - CPU quota (configurable, default 50%)
  - hard timeout (configurable, default 30 s)
  - auto-remove on exit
  - no Docker socket inside the container
  - stdout/stderr capped to prevent log flooding

The LLM-supplied code NEVER runs outside this container.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from config import get_settings

logger = logging.getLogger(__name__)


class SandboxError(Exception):
    pass


class SandboxService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._docker = None
        self.available: bool = self._check_docker()

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------
    def _check_docker(self) -> bool:
        try:
            import docker  # type: ignore
            client = docker.from_env()
            client.ping()
            self._docker = client
            logger.info("Docker sandbox available")
            return True
        except Exception as exc:
            logger.warning(
                "Docker not available — sandboxed tools disabled: %s", exc
            )
            return False

    def _get_docker(self):
        if self._docker is None:
            import docker  # type: ignore
            self._docker = docker.from_env()
        return self._docker

    # ------------------------------------------------------------------
    # Python execution
    # ------------------------------------------------------------------
    async def run_python(
        self,
        code: str,
        workspace_path: str = "",
    ) -> dict:
        """
        Execute Python code in an isolated Docker container.
        Returns dict with stdout, stderr, exit_code, timed_out, duration_ms, container_id.
        """
        if not self.available:
            raise SandboxError("Docker sandbox is not available")

        # Create an isolated temp workspace for this run
        run_id = uuid.uuid4().hex
        tmp_dir = os.path.join(
            tempfile.gettempdir(), f"sovereign_sandbox_{run_id}"
        )
        os.makedirs(tmp_dir, exist_ok=True)

        # Copy any workspace files so the agent's data is accessible
        if workspace_path and os.path.isdir(workspace_path):
            for item in os.listdir(workspace_path):
                src = os.path.join(workspace_path, item)
                dst = os.path.join(tmp_dir, item)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)

        # Write code to a file (avoids shell-injection via -c "...")
        code_file = os.path.join(tmp_dir, "_agent_code.py")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._run_container_sync,
                tmp_dir,
                run_id,
            )
            return result
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _run_container_sync(self, tmp_dir: str, run_id: str) -> dict:
        """
        Blocking Docker container execution.
        Must be called from an executor thread, not the event loop.
        """
        import docker  # type: ignore

        settings = self.settings
        t_start = time.monotonic()
        container = None

        try:
            client = self._get_docker()
            container = client.containers.run(
                image=settings.sandbox_image,
                # Execute from the code file — not via shell -c (no shell injection)
                command=["python", "/workspace/_agent_code.py"],
                detach=True,
                remove=False,
                # --- Resource limits ---
                mem_limit=f"{settings.sandbox_mem_limit_mb}m",
                memswap_limit=f"{settings.sandbox_mem_limit_mb}m",
                cpu_period=100_000,
                cpu_quota=settings.sandbox_cpu_quota,
                pids_limit=50,
                # --- Security hardening ---
                network_mode="none",          # NO network
                read_only=True,               # read-only root FS
                user="1000:1000",             # non-root
                cap_drop=["ALL"],             # drop ALL capabilities
                security_opt=["no-new-privileges"],
                # --- Workspace (writable) ---
                volumes={tmp_dir: {"bind": "/workspace", "mode": "rw"}},
                working_dir="/workspace",
                # --- No Docker socket inside ---
                # (docker.sock deliberately NOT mounted)
            )

            # Wait with hard timeout
            timed_out = False
            try:
                result = container.wait(timeout=settings.sandbox_timeout_s)
                exit_code: int = result.get("StatusCode", -1)
            except Exception:
                try:
                    container.kill()
                except Exception:
                    pass
                timed_out = True
                exit_code = -1

            # Collect output — cap to prevent log flooding
            stdout = container.logs(stdout=True, stderr=False).decode(
                "utf-8", errors="replace"
            )[:20_000]
            stderr = container.logs(stdout=False, stderr=True).decode(
                "utf-8", errors="replace"
            )[:4_000]

            duration_ms = int((time.monotonic() - t_start) * 1000)
            container_id = container.id[:12] if container.id else ""

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "duration_ms": duration_ms,
                "container_id": container_id,
            }

        except Exception as exc:
            duration_ms = int((time.monotonic() - t_start) * 1000)
            logger.exception("Sandbox container execution failed: %s", exc)
            raise SandboxError(f"Container execution failed: {exc}") from exc

        finally:
            # Always remove the container
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
