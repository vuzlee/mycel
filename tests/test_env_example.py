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
    "GRAFANA_ADMIN_USER",
    "GRAFANA_ADMIN_PASSWORD",
}


def test_every_key_is_a_setting_or_read_by_a_container() -> None:
    keys = re.findall(r"^([A-Z_]+)=", Path(".env.example").read_text(), re.M)
    unknown = {k for k in keys if k.lower() not in Settings.model_fields} - NOT_SETTINGS
    assert unknown == set()


def test_prod_with_a_dev_value_is_broken() -> None:
    env = Settings().model_copy(
        update={"mycel_env": "prod", "litellm_master_key": SecretStr("sk-mycel-dev")}
    )
    assert "LITELLM_MASTER_KEY" in dev_values(env)
    assert any(c.name == "dev values" for c in declared(env))


def test_no_way_to_sign_in_is_broken() -> None:
    env = Settings().model_copy(update={"smtp_host": None, "google_client_id": None})
    assert any(c.name == "any way in" for c in declared(env))


def test_store_urls_are_built_from_one_password_each() -> None:
    env = Settings().model_copy(
        update={
            "postgres_password": SecretStr("p@ss"),
            "mycel_app_password": None,
            "database_url_override": "",
            "migration_database_url_override": "",
            "rabbitmq_url_override": "",
            "rabbitmq_password": SecretStr("r"),
        }
    )
    assert env.database_url == env.migration_database_url
    assert ":p%40ss@" in env.database_url
    assert env.rabbitmq_url.startswith("amqp://mycel:r@")


def test_the_app_connects_as_mycel_app_when_its_password_is_set() -> None:
    env = Settings().model_copy(
        update={"mycel_app_password": SecretStr("a"), "database_url_override": ""}
    )
    assert env.database_url.startswith("postgresql://mycel_app:a@")
    assert not env.migration_database_url.startswith("postgresql://mycel_app")


def test_the_app_holding_the_master_key_is_broken() -> None:
    same = SecretStr("sk-x")
    env = Settings().model_copy(update={"litellm_master_key": same, "litellm_api_key": same})
    assert any(c.name == "gateway key" for c in declared(env))
