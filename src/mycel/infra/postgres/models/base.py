"""The declarative base and the four schema names.

One schema per layer, so a grant can follow the layer boundary.
"""

from sqlalchemy.orm import DeclarativeBase

BRONZE = "bronze"
SILVER = "silver"
GOLD = "gold"
APP = "app"


class Base(DeclarativeBase):
    """Declarative base. `alembic` autogenerates against this metadata."""
