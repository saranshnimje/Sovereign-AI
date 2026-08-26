"""
Unit tests for SandboxService.
Docker is mocked — these tests verify the security configuration
passed to Docker, not actual container execution.
"""
import pytest
from unittest.mock import MagicMock, patch


def _make_sandbox():
    with patch("services.sandbox_service.SandboxService._check_docker", return_value=True):
        from services.sandbox_service import SandboxService
        svc = SandboxService()
        svc.available = True
        return svc


def test_sandbox_unavailable_when_docker_missing():
    with patch("services.sandbox_service.SandboxService._check_docker", return_value=False):
        from services.sandbox_service import SandboxService
        svc = SandboxService()
        assert svc.available is False


@pytest.mark.asyncio
async def test_run_python_raises_when_unavailable():
    from services.sandbox_service import SandboxError
    with patch("services.sandbox_service.SandboxService._check_docker", return_value=False):
        from services.sandbox_service import SandboxService
        svc = SandboxService()
        svc.available = False
        with pytest.raises(SandboxError, match="not available"):
            await svc.run_python("print('hi')")


def test_container_run_uses_correct_security_config():
    """Verify the security parameters passed to Docker containers."""
    import tempfile, os
    svc = _make_sandbox()

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b"output"
    mock_container.id = "abc123456789"
    mock_container.remove = MagicMock()

    mock_docker = MagicMock()
    mock_docker.containers.run.return_value = mock_container
    svc._docker = mock_docker

    with tempfile.TemporaryDirectory() as tmp:
        result = svc._run_container_sync(tmp, "test_run")

    call_kwargs = mock_docker.containers.run.call_args[1]

    # Verify security hardening
    assert call_kwargs["network_mode"] == "none",       "network must be disabled"
    assert call_kwargs["read_only"] is True,            "root FS must be read-only"
    assert call_kwargs["user"] == "1000:1000",          "must run as non-root"
    assert "ALL" in call_kwargs["cap_drop"],            "must drop all capabilities"
    assert "no-new-privileges" in call_kwargs["security_opt"], "no new privileges"
    # Verify resource limits are set
    assert "mem_limit" in call_kwargs
    assert "pids_limit" in call_kwargs
    assert call_kwargs["pids_limit"] == 50


def test_container_run_command_uses_file_not_shell():
    """Code must be executed via python file, not via shell -c (injection prevention)."""
    import tempfile
    svc = _make_sandbox()

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b""
    mock_container.id = "abc123"
    mock_container.remove = MagicMock()

    mock_docker = MagicMock()
    mock_docker.containers.run.return_value = mock_container
    svc._docker = mock_docker

    with tempfile.TemporaryDirectory() as tmp:
        svc._run_container_sync(tmp, "run_id")

    call_args = mock_docker.containers.run.call_args
    command = call_args[1].get("command") or call_args[0][1]

    # Must be a list like ["python", "/workspace/_agent_code.py"]
    # NOT ["sh", "-c", "python -c '...'"]
    assert isinstance(command, list), "command must be a list"
    assert "sh" not in command,       "must not use shell"
    assert "-c" not in command,       "must not use shell -c (injection risk)"
    assert command[0] == "python"
    assert "_agent_code.py" in command[-1]


def test_container_always_removed_on_success():
    """Container must be removed even on success."""
    import tempfile
    svc = _make_sandbox()

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b"ok"
    mock_container.id = "abc"
    mock_docker = MagicMock()
    mock_docker.containers.run.return_value = mock_container
    svc._docker = mock_docker

    with tempfile.TemporaryDirectory() as tmp:
        svc._run_container_sync(tmp, "r1")

    mock_container.remove.assert_called()


def test_container_always_removed_on_timeout():
    """Container must be removed even if it times out."""
    import tempfile
    svc = _make_sandbox()

    mock_container = MagicMock()
    mock_container.wait.side_effect = Exception("timeout")  # simulate timeout
    mock_container.logs.return_value = b""
    mock_container.id = "abc"
    mock_docker = MagicMock()
    mock_docker.containers.run.return_value = mock_container
    svc._docker = mock_docker

    with tempfile.TemporaryDirectory() as tmp:
        result = svc._run_container_sync(tmp, "r1")

    assert result["timed_out"] is True
    mock_container.remove.assert_called()


def test_no_docker_socket_in_container():
    """Docker socket must NOT be mounted inside sandbox containers."""
    import tempfile
    svc = _make_sandbox()

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b""
    mock_container.id = "abc"
    mock_docker = MagicMock()
    mock_docker.containers.run.return_value = mock_container
    svc._docker = mock_docker

    with tempfile.TemporaryDirectory() as tmp:
        svc._run_container_sync(tmp, "r1")

    call_kwargs = mock_docker.containers.run.call_args[1]
    volumes = call_kwargs.get("volumes", {})
    mounted_paths = list(volumes.keys())

    # Docker socket must never appear in volume mounts
    for p in mounted_paths:
        assert "docker.sock" not in p, "Docker socket must not be in sandbox volumes"
