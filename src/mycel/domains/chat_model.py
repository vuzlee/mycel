"""Which model a chat turn runs on: its `model_ref` turned into agent settings and, for an
own model, the endpoint and keys this run may use."""

from dataclasses import replace

from pydantic import SecretStr

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.exceptions import ModelBlocked
from mycel.agents.core.own_endpoint import OwnEndpoint
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
