"""
Settings service — stores/retrieves runtime-configurable settings.
File path is derived from config.Settings.system_settings_file (configurable
via DATA_DIR env var), not hardcoded.
"""
import json
import logging
import os

from config import get_settings as get_app_settings
from schemas.settings import SystemSettings

logger = logging.getLogger(__name__)


def _get_settings_file() -> str:
    """Always derive path from the current settings so DATA_DIR is respected."""
    return get_app_settings().system_settings_file


def load_settings() -> SystemSettings:
    """Load settings from file, falling back to defaults from config."""
    cfg = get_app_settings()
    defaults = SystemSettings(
        default_chunk_size=cfg.default_chunk_size,
        default_chunk_overlap=cfg.default_chunk_overlap,
        default_top_k=cfg.default_top_k,
        default_score_threshold=cfg.default_score_threshold,
        default_max_iterations=cfg.default_max_iterations,
        approval_timeout_minutes=cfg.approval_timeout_minutes,
        sandbox_timeout_s=cfg.sandbox_timeout_s,
        sandbox_mem_limit_mb=cfg.sandbox_mem_limit_mb,
        sandbox_cpu_quota=cfg.sandbox_cpu_quota,
        max_upload_size_mb=cfg.max_upload_size_mb,
    )

    path = _get_settings_file()
    if not os.path.exists(path):
        return defaults

    try:
        with open(path) as f:
            data = json.load(f)
        merged = defaults.model_dump()
        merged.update({k: v for k, v in data.items() if k in merged})
        return SystemSettings(**merged)
    except Exception as exc:
        logger.warning("Could not load settings file %s: %s", path, exc)
        return defaults


def save_settings(settings: SystemSettings) -> None:
    """Persist settings to file (path from config)."""
    path = _get_settings_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(settings.model_dump(), f, indent=2)
    logger.info("System settings saved to %s", path)
