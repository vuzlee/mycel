"""Models a person adds with their own keys: an OpenAI-compatible base URL, a model id, keys.

Keys are sealed before they reach the database and never leave it again: a response shows
the last four characters, and a run unseals them only for itself (see `own_model_run.py`).
"""

from dataclasses import dataclass

from mycel.infra.postgres.repositories.models import ModelPrefRepository
from mycel.infra.postgres.repositories.own_models import OwnKey, OwnModelRepository, OwnModelRow
from mycel.infra.postgres.session import session_scope
from mycel.services import tokens, url_guard
from mycel.services.models import OWN

#: Enough for a handful of providers each; a list longer than this is a mistake.
MAX_MODELS = 10
#: Enough to rotate several free-tier keys of one provider.
MAX_KEYS = 5


#: Base URLs the form offers; any other https endpoint works too.
PRESETS: dict[str, str] = {
    "Gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "OpenRouter": "https://openrouter.ai/api/v1",
    "OpenAI": "https://api.openai.com/v1",
    "Ollama (LAN)": "http://ollama:11434/v1",
    "vLLM (LAN)": "http://vllm:8000/v1",
}


class OwnModelRefused(Exception):
    """The request breaks a rule a person can fix: too many, no key, a bad URL."""


class OwnModelNotFound(Exception):
    """Not this person's model, or no such model; the two are not told apart."""


@dataclass(frozen=True, slots=True)
class OwnModelView:
    """What a response may show: everything but the keys themselves."""

    id: int
    ref: str
    label: str
    model_id: str
    api_base: str
    key_hints: list[str]


def own_ref(model_id: int) -> str:
    return f"{OWN}:{model_id}"


def own_id(ref: str) -> int | None:
    """The row id an `own:<id>` ref names, or None for any other ref."""
    source, _, raw = ref.partition(":")
    return int(raw) if source == OWN and raw.isdigit() else None


def hint(key: str) -> str:
    return f"…{key[-4:]}" if len(key) > 8 else "…"


def _view(row: OwnModelRow) -> OwnModelView:
    return OwnModelView(
        id=row.id,
        ref=own_ref(row.id),
        label=row.label,
        model_id=row.model_id,
        api_base=row.api_base,
        key_hints=[k.hint for k in row.keys],
    )


def _sealed(keys: list[str]) -> list[OwnKey]:
    cleaned = [k.strip() for k in keys if k.strip()]
    if not cleaned:
        raise OwnModelRefused("add at least one API key")
    if len(cleaned) > MAX_KEYS:
        raise OwnModelRefused(f"at most {MAX_KEYS} keys per model")
    return [OwnKey(i, tokens.seal(k), hint(k)) for i, k in enumerate(cleaned)]


async def _checked_base(api_base: str) -> str:
    base = api_base.strip().rstrip("/")
    try:
        await url_guard.check(base)
    except url_guard.BlockedUrl as exc:
        raise OwnModelRefused(str(exc)) from None
    return base


async def list_own(owner_id: int) -> list[OwnModelView]:
    async with session_scope() as session:
        return [_view(r) for r in await OwnModelRepository(session).all_of(owner_id)]


async def add_own(
    owner_id: int, label: str, model_id: str, api_base: str, keys: list[str]
) -> OwnModelView:
    base = await _checked_base(api_base)
    sealed = _sealed(keys)
    async with session_scope() as session:
        repo = OwnModelRepository(session)
        if await repo.count(owner_id) >= MAX_MODELS:
            raise OwnModelRefused(f"at most {MAX_MODELS} models of your own")
        new_id = await repo.add(owner_id, label.strip(), model_id.strip(), base, sealed)
        found = await repo.one(owner_id, new_id)
    assert found is not None
    return _view(found)


async def edit_own(
    owner_id: int,
    model_id: int,
    label: str,
    endpoint_model: str,
    api_base: str,
    keys: list[str] | None,
) -> OwnModelView:
    """`keys=None` keeps the stored keys: they are never sent back to be resent."""
    base = await _checked_base(api_base)
    sealed = _sealed(keys) if keys is not None else None
    async with session_scope() as session:
        repo = OwnModelRepository(session)
        if not await repo.update(
            owner_id, model_id, label.strip(), endpoint_model.strip(), base, sealed
        ):
            raise OwnModelNotFound(model_id)
        found = await repo.one(owner_id, model_id)
    assert found is not None
    return _view(found)


async def remove_own(owner_id: int, model_id: int) -> None:
    async with session_scope() as session:
        if not await OwnModelRepository(session).remove(owner_id, model_id):
            raise OwnModelNotFound(model_id)
        await ModelPrefRepository(session).forget(own_ref(model_id))
