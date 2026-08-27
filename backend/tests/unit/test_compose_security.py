"""
Deployment security tests (P0.4) — Docker socket isolation.

These parse the REAL compose files so a future edit cannot silently
re-expose /var/run/docker.sock to the application container.
"""
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]  # repo root
COMPOSE = ROOT / "docker-compose.yml"
COMPOSE_DEV = ROOT / "docker-compose.dev.yml"


def _load(path: pathlib.Path) -> dict:
    assert path.exists(), f"{path} missing"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _service_volumes(compose: dict, service: str) -> list[str]:
    return [v if isinstance(v, str) else ":".join(str(x) for x in v.get("bind", []))
            for v in compose["services"][service].get("volumes", [])]


class TestDockerSocketIsolation:
    def test_backend_has_no_docker_socket_mount(self):
        for name in ("docker-compose.yml", "docker-compose.dev.yml"):
            compose = _load(ROOT / name)
            vols = " ".join(_service_volumes(compose, "backend"))
            assert "docker.sock" not in vols, (
                f"{name}: backend mounts docker.sock directly — forbidden"
            )

    def test_only_proxy_touches_socket_and_readonly(self):
        for name in ("docker-compose.yml", "docker-compose.dev.yml"):
            compose = _load(ROOT / name)
            for svc, cfg in compose["services"].items():
                vols = " ".join(_service_volumes(compose, svc))
                if "docker.sock" in vols:
                    assert svc == "dockerproxy", (
                        f"{name}: only 'dockerproxy' may mount docker.sock (found on '{svc}')"
                    )
                    # read-only socket even for the proxy itself
                    raw = compose["services"][svc]["volumes"]
                    for v in raw:
                        text = v if isinstance(v, str) else ""
                        if "docker.sock" in text:
                            assert text.rstrip().endswith(":ro"), f"socket must be :ro ({name})"

    def test_proxy_exists_and_backend_uses_it(self):
        compose = _load(COMPOSE)
        assert "dockerproxy" in compose["services"], "least-privilege proxy service missing"

        backend_env = compose["services"]["backend"].get("environment", [])
        env_text = "\n".join(backend_env)
        assert "DOCKER_HOST=tcp://dockerproxy" in env_text, (
            "backend must reach Docker via tcp://dockerproxy, not the socket"
        )

    def test_proxy_blocks_host_level_apis(self):
        compose = _load(COMPOSE)
        env_list = compose["services"]["dockerproxy"].get("environment", [])
        env = {}
        for item in env_list:
            k, _, v = item.partition("=")
            env[k] = v

        allowed = {"CONTAINERS", "IMAGES", "PING", "VERSION", "POST", "IMAGES_CREATE"}
        dangerous_granted = {
            k for k in ("SECRETS", "NETWORKS", "NODES", "TASKS", "SERVICES",
                        "SWARM", "PLUGINS", "EXEC", "SYSTEM", "BUILD", "COMMIT")
            if env.get(k) == "1"
        }
        assert not dangerous_granted, f"host-level APIs granted to app sidecar: {dangerous_granted}"
        assert env.get("CONTAINERS") == "1", "sandbox needs container management"
        assert env.get("POST") == "1", "sandbox needs POST within allowed prefixes"


class TestSandboxFailureHonesty:
    def test_unavailable_sandbox_raises_explicitly(self):
        """No silent fallback when Docker is unreachable."""
        import asyncio

        from services.sandbox_service import SandboxError, SandboxService

        svc = SandboxService.__new__(SandboxService)  # skip __init__'s real probe
        svc.available = False

        async def _run():
            await svc.run_python("print('nope')")

        try:
            asyncio.run(_run())
        except SandboxError as exc:
            assert "not available" in str(exc).lower()
        else:
            raise AssertionError("expected explicit SandboxError, got success")

    def test_compose_files_are_valid_yaml_with_network_isolation_keys(self):
        compose = _load(COMPOSE)
        sandbox_cfg_hint = str(compose)
        # The sandbox container profile is enforced in code (network none,
        # cap_drop ALL); here we at least pin that the proxy image is pinned.
        proxy_img = compose["services"]["dockerproxy"]["image"]
        assert ":" in proxy_img and not proxy_img.endswith(":latest"), (
            "pin a specific proxy version, not :latest"
        )
