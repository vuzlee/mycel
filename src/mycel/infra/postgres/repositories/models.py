"""Which models a person turned off, and which one is their default."""

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import ModelPref, User


class ModelPrefRepository:
    """Reads and writes on a caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set_toggle(self, user_id: int, model_ref: str, enabled: bool) -> None:
        stmt = insert(ModelPref).values(user_id=user_id, model_ref=model_ref, enabled=enabled)
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[ModelPref.user_id, ModelPref.model_ref],
                set_={"enabled": stmt.excluded.enabled},
            )
        )

    async def forget(self, model_ref: str) -> None:
        """Drop every toggle and default naming a model that no longer exists."""
        await self._session.execute(delete(ModelPref).where(ModelPref.model_ref == model_ref))
        await self._session.execute(
            update(User).where(User.default_model_ref == model_ref).values(default_model_ref=None)
        )

    async def toggles_and_default(self, user_id: int) -> tuple[dict[str, bool], str | None]:
        """Every toggle this person set (missing means untouched), and their default model.

        One round trip: the user row with its toggles joined on.
        """
        rows = await self._session.execute(
            select(User.default_model_ref, ModelPref.model_ref, ModelPref.enabled)
            .outerjoin(ModelPref, ModelPref.user_id == User.id)
            .where(User.id == user_id)
        )
        default: str | None = None
        toggles: dict[str, bool] = {}
        for chosen, ref, enabled in rows.tuples():
            default = chosen
            if ref is not None:
                toggles[ref] = enabled
        return toggles, default

    async def set_default(self, user_id: int, model_ref: str | None) -> None:
        await self._session.execute(
            update(User).where(User.id == user_id).values(default_model_ref=model_ref)
        )
