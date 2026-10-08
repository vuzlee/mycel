"""The declarative base and one schema name per layer."""

from sqlalchemy.orm import DeclarativeBase

BRONZE = "bronze"
SILVER = "silver"
GOLD = "gold"
APP = "app"


class Base(DeclarativeBase):
    """Declarative base; alembic autogenerates against its metadata."""
