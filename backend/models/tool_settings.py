"""
Tool and Plugin persistence — runtime overrides over code-defined definitions.

Design:
- Code (tools/registry.py, services/plugin_manifests.py) is the source of truth
  for metadata: schemas, risk, permissions, categories.
- These tables store ONLY operator state: enabled flag + JSON configuration.
- A plugin that is disabled makes ALL tools it provides unavailable.
- Tables are new → created safely by Base.metadata.create_all.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from database import Base, UTCDateTime


class ToolSetting(Base):
    __tablename__ = "tool_settings"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Operator configuration. Secrets inside are NEVER returned unmasked.
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class PluginSetting(Base):
    __tablename__ = "plugin_settings"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
