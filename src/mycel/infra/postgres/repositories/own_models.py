"""A person's own models and their sealed keys. Every read is filtered by owner."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import OwnModel, OwnModelKey


@dataclass(frozen=True, slots=True)
class OwnKey:
    position: int
    key_sealed: str
    hint: str


@dataclass(frozen=True, slots=True)
class OwnModelRow:
    id: int
    owner_id: int
    label: str
    model_id: str
    api_base: str
    created_at: datetime
    keys: tuple[OwnKey, ...]


class OwnModelRepository:
    """Reads and writes on a caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count(self, owner_id: int) -> int:
        found = await self._session.scalar(
            select(func.count()).select_from(OwnModel).where(OwnModel.owner_id == owner_id)
        )
        return int(found or 0)

    async def labels_of(self, owner_id: int) -> list[tuple[int, str]]:
        """Id and label of each, oldest first: what a picker shows, without the sealed keys."""
        rows = await self._session.execute(
            select(OwnModel.id, OwnModel.label)
            .where(OwnModel.owner_id == owner_id)
            .order_by(OwnModel.id)
        )
        return [(i, label) for i, label in rows.tuples()]

    async def all_of(self, owner_id: int) -> list[OwnModelRow]:
        rows = await self._session.scalars(
            select(OwnModel).where(OwnModel.owner_id == owner_id).order_by(OwnModel.id)
        )
        models = list(rows)
        keys = await self._keys([m.id for m in models])
        return [_row(m, keys.get(m.id, ())) for m in models]

    async def one(self, owner_id: int, model_id: int) -> OwnModelRow | None:
        """The model, only if it is this person's."""
        found = await self._session.scalar(
            select(OwnModel).where(OwnModel.id == model_id, OwnModel.owner_id == owner_id)
        )
        if found is None:
            return None
        return _row(found, (await self._keys([found.id])).get(found.id, ()))

    async def add(
        self, owner_id: int, label: str, model_id: str, api_base: str, keys: list[OwnKey]
    ) -> int:
        row = OwnModel(owner_id=owner_id, label=label, model_id=model_id, api_base=api_base)
        self._session.add(row)
        await self._session.flush()
        await self._set_keys(row.id, keys)
        return row.id

    async def update(
        self,
        owner_id: int,
        model_id: int,
        label: str,
        endpoint_model: str,
        api_base: str,
        new_keys: list[OwnKey],
    ) -> bool:
        """New keys go after the stored ones; nothing stored is replaced."""
        found = await self._session.scalar(
            select(OwnModel).where(OwnModel.id == model_id, OwnModel.owner_id == owner_id)
        )
        if found is None:
            return False
        found.label, found.model_id, found.api_base = label, endpoint_model, api_base
        if new_keys:
            stored = await self._keys([model_id])
            start = max((k.position for k in stored.get(model_id, ())), default=-1) + 1
            self._session.add_all(
                OwnModelKey(
                    own_model_id=model_id,
                    position=start + i,
                    key_sealed=k.key_sealed,
                    hint=k.hint,
                )
                for i, k in enumerate(new_keys)
            )
            await self._session.flush()
        return True

    async def remove(self, owner_id: int, model_id: int) -> bool:
        """Delete the model and, by cascade, every sealed key: nothing is kept."""
        result = await self._session.execute(
            delete(OwnModel).where(OwnModel.id == model_id, OwnModel.owner_id == owner_id)
        )
        return bool(getattr(result, "rowcount", 0))

    async def remove_key(self, owner_id: int, model_id: int, index: int) -> bool:
        """Drop the key at this place in the list; False if there is no such key."""
        found = await self.one(owner_id, model_id)
        if found is None or not 0 <= index < len(found.keys):
            return False
        await self._session.execute(
            delete(OwnModelKey).where(
                OwnModelKey.own_model_id == model_id,
                OwnModelKey.position == found.keys[index].position,
            )
        )
        return True

    async def _set_keys(self, model_id: int, keys: list[OwnKey]) -> None:
        await self._session.execute(delete(OwnModelKey).where(OwnModelKey.own_model_id == model_id))
        self._session.add_all(
            OwnModelKey(
                own_model_id=model_id, position=k.position, key_sealed=k.key_sealed, hint=k.hint
            )
            for k in keys
        )
        await self._session.flush()

    async def _keys(self, ids: list[int]) -> dict[int, tuple[OwnKey, ...]]:
        if not ids:
            return {}
        rows = await self._session.scalars(
            select(OwnModelKey)
            .where(OwnModelKey.own_model_id.in_(ids))
            .order_by(OwnModelKey.own_model_id, OwnModelKey.position)
        )
        found: dict[int, list[OwnKey]] = {}
        for k in rows:
            found.setdefault(k.own_model_id, []).append(OwnKey(k.position, k.key_sealed, k.hint))
        return {i: tuple(v) for i, v in found.items()}


def _row(m: OwnModel, keys: tuple[OwnKey, ...]) -> OwnModelRow:
    return OwnModelRow(
        id=m.id,
        owner_id=m.owner_id,
        label=m.label,
        model_id=m.model_id,
        api_base=m.api_base,
        created_at=m.created_at,
        keys=keys,
    )
