"""
UserModelPrefs ORM model — per-user preferred chat model.

Lets each user pick a default model (provider + model id) that is restored
when they open Chat. Strictly per-user: one row per user_id.
New table — created automatically for existing databases by create_all.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from database import Base, UTCDateTime


class UserModelPref(Base):
    __tablename__ = "user_model_prefs"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<UserModelPref user={self.user_id[:8]} model={self.model_name}>"
