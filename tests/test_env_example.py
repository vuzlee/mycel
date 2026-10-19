"""`.env.example` names only settings that exist, and doctor catches dev values in prod."""

import re
from pathlib import Path

from pydantic import SecretStr

from mycel.core.config import Settings
from mycel.doctor.declared import declared, dev_values

#: Read by containers, not by Settings.
NOT_SETTINGS = {
    "DEFAULT_MODEL_API_KEY",
    "DEFAULT_MODEL_BASE_URL",
    "POSTGRES_PASSWORD",
    "RABBITMQ_PASSWORD",
    "GRAFANA_ADMIN_USER",
    "GRAFANA_ADMIN_PASSWORD",
}


def test_every_key_is_a_setting_or_read_by_a_container() -> None:
    keys = re.findall(r"^([A-Z_]+)=", Path(".env.example").read_text(), re.M)
    unknown = {k for k in keys if k.lower() not in Settings.model_fields} - NOT_SETTINGS
    assert unknown == set()


def test_prod_with_a_dev_value_is_broken() -> None:
    env = Settings().model_copy(
        update={"mycel_env": "prod", "litellm_api_key": SecretStr("sk-mycel-dev")}
    )
    assert "LITELLM_API_KEY" in dev_values(env)
    assert any(c.name == "dev values" for c in declared(env))


def test_no_way_to_sign_in_is_broken() -> None:
    env = Settings().model_copy(update={"smtp_host": None, "google_client_id": None})
    assert any(c.name == "any way in" for c in declared(env))
