"""Which model a chat turn runs on: its `model_ref` turned into agent settings and, for an
own model, the endpoint and keys this run may use."""

from dataclasses import dataclass, replace

from pydantic import SecretStr

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.exceptions import (
    ModelAuth,
    ModelBlocked,
    ModelCallFailed,
    ModelNotFound,
    ModelProviderError,
    ModelQuota,
    ModelTimeout,
    ModelUnreachable,
    translate_agent_errors,
)
from mycel.agents.core.model_builder import build_own_model
from mycel.agents.core.own_endpoint import OwnEndpoint
from mycel.core import redact
from mycel.core.exceptions import ConfigError
from mycel.infra.postgres.repositories.own_models import OwnModelRepository
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis import key_rotation
from mycel.services import models, tokens, url_guard
from mycel.services.own_models import own_id


def model_settings(agent: str, model_ref: str) -> AgentSettings:
    """The agent's own settings, on the model the turn picked.

    An own model keeps the agent's settings as they are: `MycelDeps.own` carries the model.
    """
    cfg = AgentSettings.from_config(agent)
    if own_id(model_ref) is not None:
        return cfg
    name = models.gateway_name(model_ref)
    if name is None:
        raise ConfigError(f"no model behind {model_ref}")
    return replace(cfg, model_spec=f"cloud:{name}")


async def own_endpoint(owner_id: int, model_ref: str) -> OwnEndpoint | None:
    """The endpoint and unsealed keys for this run, or None for a host model.

    The base URL is checked again: what it resolves to may have changed since it was saved.
    Keys cooling down after a quota or auth failure go last, not away, so a run with every
    key cooling still tries them rather than failing unasked.
    """
    model_id = own_id(model_ref)
    if model_id is None:
        return None
    async with session_scope() as session:
        row = await OwnModelRepository(session).one(owner_id, model_id)
    if row is None or not row.keys:
        raise ConfigError(f"{model_ref} is not a model this person has")
    try:
        await url_guard.check(row.api_base)
    except url_guard.BlockedUrl as exc:
        raise ModelBlocked(f"{row.label}: base URL not allowed: {exc}") from None

    count = len(row.keys)
    start = await key_rotation.next_start(model_id, count)
    cooling = await key_rotation.cooling(model_id, count)
    turned = row.keys[start:] + row.keys[:start]
    ordered = [k for k in turned if k.position not in cooling] + [
        k for k in turned if k.position in cooling
    ]
    return OwnEndpoint(
        model_id=model_id,
        label=row.label,
        api_base=row.api_base,
        endpoint_model=row.model_id,
        keys=tuple((k.position, SecretStr(tokens.unseal(k.key_sealed))) for k in ordered),
    )


@dataclass(frozen=True, slots=True)
class KeyCheck:
    hint: str
    ok: bool
    #: `quota`, `auth`, `not_found`, `unreachable` or `provider`; None when it answered.
    kind: str | None
    detail: str


_KINDS: tuple[tuple[type[ModelCallFailed], str], ...] = (
    (ModelQuota, "quota"),
    (ModelAuth, "auth"),
    (ModelNotFound, "not_found"),
    (ModelUnreachable, "unreachable"),
    (ModelProviderError, "provider"),
)


async def test_keys(owner_id: int, model_ref: str) -> list[KeyCheck]:
    """One one-token request per key, in stored order, so a person sees which key works.

    No rotation and no cooldown: each key answers for itself, and a test sets none aside.
    """
    own = await own_endpoint(owner_id, model_ref)
    if own is None:
        raise ConfigError(f"{model_ref} is not an own model")
    hints = await _hints(owner_id, own.model_id)
    checks = []
    for position, key in sorted(own.keys, key=lambda pk: pk[0]):
        checks.append(await _one_key(replace(own, keys=((position, key),)), hints[position]))
    return checks


async def _hints(owner_id: int, model_id: int) -> dict[int, str]:
    async with session_scope() as session:
        row = await OwnModelRepository(session).one(owner_id, model_id)
    return {k.position: k.hint for k in row.keys} if row else {}


async def _one_key(own: OwnEndpoint, hint: str) -> KeyCheck:
    from pydantic_ai.messages import ModelRequest
    from pydantic_ai.models import ModelRequestParameters

    async def keep(*_: object) -> None:
        return None

    cfg = replace(AgentSettings(), max_tokens=1, timeout_s=15.0)
    model, clients = build_own_model(own, cfg, keep, rotate=False)
    try:
        with redact.holding(own.keys[0][1].get_secret_value()), translate_agent_errors(own.label):
            await model.request(
                [ModelRequest.user_text_prompt("Reply with one word.")],
                None,
                ModelRequestParameters(),
            )
    except ModelCallFailed as exc:
        kind = next((name for cls, name in _KINDS if isinstance(exc, cls)), None)
        return KeyCheck(hint, False, kind, redact.scrub(str(exc)))
    except ModelTimeout:
        return KeyCheck(hint, False, "unreachable", "no answer in 15 seconds")
    finally:
        for client in clients:
            await client.close()
    return KeyCheck(hint, True, None, "answered")
