"""Which models a person may pick, and which one answers when they pick none.

A `model_ref` names a model in one string: `host:<gateway name>` for a model in
`host_models`, `own:<id>` for one a person added (batch 090).
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.config import Settings, get_settings
from mycel.infra.postgres.repositories.models import ModelPrefRepository
from mycel.infra.postgres.repositories.own_models import OwnModelRepository
from mycel.infra.postgres.session import session_scope

HOST = "host"
OWN = "own"


class UnknownModel(Exception):
    """The ref names no model this person may use."""


class LastModel(Exception):
    """Turning this off would leave nothing to answer with."""


@dataclass(frozen=True, slots=True)
class ModelChoice:
    """One row of the picker."""

    ref: str
    label: str
    source: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class Models:
    """Everything the Settings tab and the composer show."""

    choices: list[ModelChoice]
    default_ref: str


def host_ref(name: str) -> str:
    return f"{HOST}:{name}"


async def labels_for(user_id: int) -> dict[str, str]:
    """Every ref this person's turns may name, host and own, to the label it shows as."""
    async with session_scope() as session:
        own = await OwnModelRepository(session).all_of(user_id)
    labels = {host_ref(m.name): m.label for m in get_settings().host_models}
    labels.update({f"{OWN}:{m.id}": m.label for m in own})
    return labels


def gateway_name(ref: str, settings: Settings | None = None) -> str | None:
    """The gateway `model_name` a host ref points at, or None if it is not a host model."""
    source, _, name = ref.partition(":")
    names = {m.name for m in (settings or get_settings()).host_models}
    return name if source == HOST and name in names else None


def _choices(
    toggles: dict[str, bool], own: list[tuple[int, str]], settings: Settings
) -> list[ModelChoice]:
    """Host models first, then the person's own; a model with no toggle is on."""
    hosted = [(host_ref(m.name), m.label, HOST) for m in settings.host_models]
    owned = [(f"{OWN}:{i}", label, OWN) for i, label in own]
    return [
        ModelChoice(ref=ref, label=label, source=source, enabled=toggles.get(ref, True))
        for ref, label, source in hosted + owned
    ]


async def _load(session: AsyncSession, user_id: int) -> tuple[list[ModelChoice], str | None]:
    repo = ModelPrefRepository(session)
    own = [(m.id, m.label) for m in await OwnModelRepository(session).all_of(user_id)]
    choices = _choices(await repo.toggles(user_id), own, get_settings())
    return choices, await repo.default(user_id)


def _pick_default(choices: list[ModelChoice], chosen: str | None, settings: Settings) -> str:
    """The person's default if still on, else the host default if on, else the first on."""
    on = [c.ref for c in choices if c.enabled]
    for ref in (chosen, host_ref(settings.default_host_model.name)):
        if ref in on:
            return ref
    return on[0] if on else host_ref(settings.default_host_model.name)


async def models_for(user_id: int) -> Models:
    async with session_scope() as session:
        choices, chosen = await _load(session, user_id)
    return Models(choices=choices, default_ref=_pick_default(choices, chosen, get_settings()))


async def set_enabled(user_id: int, ref: str, enabled: bool) -> Models:
    async with session_scope() as session:
        repo = ModelPrefRepository(session)
        choices, _ = await _load(session, user_id)
        if ref not in {c.ref for c in choices}:
            raise UnknownModel(ref)
        if not enabled and [c.ref for c in choices if c.enabled] == [ref]:
            raise LastModel(ref)
        await repo.set_toggle(user_id, ref, enabled)
    return await models_for(user_id)


async def set_default(user_id: int, ref: str) -> Models:
    current = await models_for(user_id)
    if ref not in {c.ref for c in current.choices if c.enabled}:
        raise UnknownModel(ref)
    async with session_scope() as session:
        await ModelPrefRepository(session).set_default(user_id, ref)
    return await models_for(user_id)


async def usable(user_id: int, ref: str | None) -> str:
    """The ref a new question is queued with; one that is off or unknown is refused."""
    current = await models_for(user_id)
    if ref is None:
        return current.default_ref
    if ref not in {c.ref for c in current.choices if c.enabled}:
        raise UnknownModel(ref)
    return ref


async def resolve(user_id: int, ref: str | None) -> tuple[str, str | None]:
    """The ref a run uses, and a warning when the asked one could not be used.

    Called before the run, so a model turned off or removed since the question was queued
    falls back to the default rather than failing the job.
    """
    current = await models_for(user_id)
    if ref is None or ref in {c.ref for c in current.choices if c.enabled}:
        return ref or current.default_ref, None
    return current.default_ref, (
        f"The model you picked ({ref}) is no longer available; "
        f"answered with {current.default_ref} instead."
    )
