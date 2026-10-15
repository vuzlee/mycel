"""Which model a chat turn runs on: its `model_ref` turned into agent settings."""

from dataclasses import replace

from mycel.agents.core.config import AgentSettings
from mycel.core.exceptions import ConfigError
from mycel.services import models


def model_settings(agent: str, model_ref: str) -> AgentSettings:
    """The agent's own settings, on the model the turn picked."""
    name = models.gateway_name(model_ref)
    if name is None:
        raise ConfigError(f"no model behind {model_ref}")
    return replace(AgentSettings.from_config(agent), model_spec=f"cloud:{name}")
