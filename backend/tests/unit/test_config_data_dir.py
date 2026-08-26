"""
Unit tests for configurable DATA_DIR / data-path resolution (P0).
"""
import os
import importlib
import sys
import pytest
from pathlib import Path
from unittest.mock import patch


def _fresh_settings(**env_overrides):
    """Import a fresh (uncached) Settings instance with patched env vars."""
    # Clear lru_cache so each call starts clean
    import config as cfg_module
    cfg_module.get_settings.cache_clear()

    with patch.dict(os.environ, env_overrides, clear=False):
        # Re-evaluate module-level _DATA_DIR and Settings
        importlib.reload(cfg_module)
        return cfg_module.get_settings()


def teardown_module(module):
    """Restore module state after tests."""
    import config as cfg_module
    cfg_module.get_settings.cache_clear()
    importlib.reload(cfg_module)


# ------------------------------------------------------------------
# DATA_DIR env var
# ------------------------------------------------------------------

def test_data_dir_overridden_by_env(tmp_path):
    """If DATA_DIR env var is set, it must be used."""
    s = _fresh_settings(DATA_DIR=str(tmp_path))
    assert s.data_dir == str(tmp_path)


def test_derived_paths_follow_data_dir(tmp_path):
    """All derived paths must be children of data_dir."""
    s = _fresh_settings(DATA_DIR=str(tmp_path))
    assert s.upload_dir.startswith(str(tmp_path))
    assert s.sandbox_workspace.startswith(str(tmp_path))
    assert s.model_roles_file.startswith(str(tmp_path))
    assert s.system_settings_file.startswith(str(tmp_path))


def test_upload_dir_is_uploads_subdir(tmp_path):
    s = _fresh_settings(DATA_DIR=str(tmp_path))
    assert Path(s.upload_dir) == Path(tmp_path) / "uploads"


def test_sandbox_workspace_is_subdir(tmp_path):
    s = _fresh_settings(DATA_DIR=str(tmp_path))
    assert Path(s.sandbox_workspace) == Path(tmp_path) / "sandbox_workspace"


def test_model_roles_file_path(tmp_path):
    s = _fresh_settings(DATA_DIR=str(tmp_path))
    assert Path(s.model_roles_file) == Path(tmp_path) / "model_roles.json"


def test_system_settings_file_path(tmp_path):
    s = _fresh_settings(DATA_DIR=str(tmp_path))
    assert Path(s.system_settings_file) == Path(tmp_path) / "system_settings.json"


def test_no_hardcoded_app_data_when_data_dir_set(tmp_path):
    """When DATA_DIR is set, /app/data must NOT appear in derived paths."""
    s = _fresh_settings(DATA_DIR=str(tmp_path))
    for attr in ["upload_dir", "sandbox_workspace", "model_roles_file", "system_settings_file"]:
        val = getattr(s, attr)
        assert "/app/data" not in val.replace("\\", "/").lower() or str(tmp_path) in val, \
            f"{attr} still references /app/data when DATA_DIR={tmp_path}"


# ------------------------------------------------------------------
# settings_service path resolution
# ------------------------------------------------------------------

def test_settings_service_uses_config_path(tmp_path):
    """save_settings must write to path derived from settings, not a hardcoded string."""
    from schemas.settings import SystemSettings

    # Directly test that save_settings writes to the path from get_settings()
    with patch("services.settings_service._get_settings_file", return_value=str(tmp_path / "system_settings.json")):
        from services import settings_service
        s = SystemSettings()
        settings_service.save_settings(s)

    assert (tmp_path / "system_settings.json").exists()


def test_settings_service_loads_from_config_path(tmp_path):
    """load_settings must read from path derived from config."""
    import json
    settings_json = {"default_chunk_size": 128, "default_chunk_overlap": 10,
                     "default_top_k": 3, "default_score_threshold": 0.5,
                     "default_max_iterations": 7, "approval_timeout_minutes": 2,
                     "sandbox_timeout_s": 15, "sandbox_mem_limit_mb": 64,
                     "sandbox_cpu_quota": 25000, "max_upload_size_mb": 10}
    settings_file = tmp_path / "system_settings.json"
    settings_file.write_text(json.dumps(settings_json))

    with patch("services.settings_service._get_settings_file", return_value=str(settings_file)):
        from services import settings_service
        loaded = settings_service.load_settings()

    assert loaded.default_chunk_size == 128
    assert loaded.default_max_iterations == 7


# ------------------------------------------------------------------
# model_service path resolution
# ------------------------------------------------------------------

def test_model_service_uses_config_path(tmp_path):
    """_save_roles must write to path derived from settings."""
    expected = tmp_path / "model_roles.json"
    with patch("services.model_service._roles_file", return_value=str(expected)):
        from services import model_service
        model_service._save_roles({"chat": "llama3.2:3b", "embedding": "nomic-embed-text"})

    assert expected.exists(), f"Expected roles file at {expected}"


def test_model_service_load_defaults_without_file():
    """If no roles file exists, _load_roles must return defaults."""
    import config as cfg_module
    cfg_module.get_settings.cache_clear()

    # Use a tmp path where no file exists
    import tempfile, shutil
    td = tempfile.mkdtemp()
    try:
        with patch.dict(os.environ, {"DATA_DIR": td}):
            importlib.reload(cfg_module)
            from services import model_service
            importlib.reload(model_service)
            roles = model_service._load_roles()
        assert "chat" in roles
        assert "embedding" in roles
    finally:
        shutil.rmtree(td, ignore_errors=True)
        cfg_module.get_settings.cache_clear()
        importlib.reload(cfg_module)
