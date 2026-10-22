"""A person's own models: sealed keys that never come back, owner-only, bounded."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.agents.core.exceptions import ModelBlocked
from mycel.core.config import get_settings
from mycel.core.exceptions import ConfigError
from mycel.domains import chat_model
from mycel.infra.postgres.models import OwnModelKey
from mycel.infra.postgres.repositories.identity import IdentityRepository
from mycel.infra.postgres.repositories.models import ModelPrefRepository
from mycel.infra.redis import key_rotation
from mycel.services import model_catalog as models
from mycel.services import own_models, url_guard
from mycel.services import sealing as tokens
from mycel.services.own_models import OwnModelNotFound, OwnModelRefused
from tests.fakes import needs_postgres

pytestmark = [pytest.mark.anyio, needs_postgres]

BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
KEY = "AIzaSy-test-key-number-one-0001"


@pytest.fixture
async def people(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> tuple[int, int]:
    """Two people; every service call runs on the test's session; DNS is not consulted."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        yield session
        await session.flush()

    async def public(url: str) -> None:
        url_guard.check_shape(url)

    for module in (own_models, models):
        monkeypatch.setattr(module, "session_scope", scope)
    monkeypatch.setattr(url_guard, "check", public)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    identity = IdentityRepository(session)
    a = (await identity.create_user("a@x.com")).id
    b = (await identity.create_user("b@x.com")).id
    return a, b


async def _add(owner: int, keys: list[str] | None = None) -> own_models.OwnModelView:
    return await own_models.add_own(owner, "My model", "gemini-3.6-flash", BASE, keys or [KEY])


class TestKeys:
    async def test_a_key_is_stored_sealed_and_shown_as_a_hint(
        self, people: tuple[int, int], session: AsyncSession
    ) -> None:
        view = await _add(people[0])
        stored = (await session.scalars(select(OwnModelKey.key_sealed))).one()

        assert KEY not in stored and tokens.unseal(stored) == KEY
        assert view.key_hints == ["…0001"]
        assert KEY not in repr(view)

    async def test_an_edit_without_keys_keeps_them(self, people: tuple[int, int]) -> None:
        view = await _add(people[0], [KEY, "AIzaSy-second-key-0002"])
        edited = await own_models.edit_own(
            people[0], view.id, "Renamed", "gemini-3.6-flash", BASE, None
        )
        assert edited.label == "Renamed" and edited.key_hints == ["…0001", "…0002"]

    async def test_no_key_is_refused(self, people: tuple[int, int]) -> None:
        with pytest.raises(OwnModelRefused, match="key"):
            await own_models.add_own(people[0], "x", "m", BASE, ["  "])

    async def test_too_many_keys_are_refused(self, people: tuple[int, int]) -> None:
        with pytest.raises(OwnModelRefused, match="5 keys"):
            await _add(people[0], [f"key-number-{i:04d}" for i in range(6)])

    async def test_one_dead_key_can_go_but_not_the_last(self, people: tuple[int, int]) -> None:
        mine, theirs = people
        view = await _add(mine, [KEY, "AIzaSy-second-key-0002"])

        with pytest.raises(OwnModelNotFound):
            await own_models.remove_key(theirs, view.id, 0)
        left = await own_models.remove_key(mine, view.id, 0)
        assert left.key_hints == ["…0002"]
        with pytest.raises(OwnModelRefused, match="at least one"):
            await own_models.remove_key(mine, view.id, 0)

    async def test_an_edit_adds_keys_after_the_stored_ones(self, people: tuple[int, int]) -> None:
        view = await _add(people[0])
        edited = await own_models.edit_own(
            people[0], view.id, "My model", "m", BASE, ["AIzaSy-second-key-0002"]
        )
        assert edited.key_hints == ["…0001", "…0002"]
        with pytest.raises(OwnModelRefused, match="5 keys"):
            await own_models.edit_own(
                people[0], view.id, "x", "m", BASE, [f"key-number-{i:04d}" for i in range(4)]
            )


class TestOwnership:
    async def test_someone_else_cannot_see_edit_or_delete_it(self, people: tuple[int, int]) -> None:
        mine, theirs = people
        view = await _add(mine)

        assert await own_models.list_own(theirs) == []
        with pytest.raises(OwnModelNotFound):
            await own_models.edit_own(theirs, view.id, "x", "m", BASE, None)
        with pytest.raises(OwnModelNotFound):
            await own_models.remove_own(theirs, view.id)

    async def test_it_is_in_its_owners_picker_only(self, people: tuple[int, int]) -> None:
        view = await _add(people[0])
        assert view.ref in {c.ref for c in (await models.models_for(people[0])).choices}
        assert view.ref not in {c.ref for c in (await models.models_for(people[1])).choices}


class TestLimitsAndRemoval:
    async def test_at_most_ten_models(self, people: tuple[int, int]) -> None:
        for _ in range(own_models.MAX_MODELS):
            await _add(people[0])
        with pytest.raises(OwnModelRefused, match="10 models"):
            await _add(people[0])

    async def test_a_bad_base_url_is_refused(self, people: tuple[int, int]) -> None:
        with pytest.raises(OwnModelRefused, match="https"):
            await own_models.add_own(people[0], "x", "m", "http://example.com/v1", [KEY])

    async def test_removal_takes_its_keys_toggle_and_default(
        self, people: tuple[int, int], session: AsyncSession
    ) -> None:
        view = await _add(people[0])
        await models.set_default(people[0], view.ref)
        await own_models.remove_own(people[0], view.id)

        assert (await session.scalars(select(OwnModelKey))).all() == []
        assert await ModelPrefRepository(session).default(people[0]) is None


class TestRotatingTheEncryptionKey:
    def test_an_old_value_opens_after_a_new_key_is_put_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", old)
        get_settings.cache_clear()
        sealed = tokens.seal("secret")

        monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", f"{new},{old}")
        get_settings.cache_clear()
        assert tokens.unseal(sealed) == "secret"
        assert Fernet(new.encode()).decrypt(tokens.seal("x").encode()) == b"x"


class TestTheEndpointARunGets:
    @pytest.fixture
    def rotation(self, monkeypatch: pytest.MonkeyPatch, session: AsyncSession) -> dict[str, Any]:
        state: dict[str, Any] = {"start": 0, "cooling": set()}

        async def next_start(model_id: int, count: int) -> int:
            return int(state["start"])

        async def cooling(model_id: int, count: int) -> set[int]:
            return set(state["cooling"])

        monkeypatch.setattr(key_rotation, "next_start", next_start)
        monkeypatch.setattr(key_rotation, "cooling", cooling)

        @asynccontextmanager
        async def scope() -> AsyncIterator[AsyncSession]:
            yield session

        monkeypatch.setattr(chat_model, "session_scope", scope)
        return state

    async def test_keys_come_unsealed_in_turn_order_cooling_last(
        self, people: tuple[int, int], rotation: dict[str, Any]
    ) -> None:
        keys = ["key-zero-0000000", "key-one-11111111", "key-two-22222222"]
        view = await _add(people[0], keys)
        rotation.update(start=1, cooling={2})

        own = await chat_model.own_endpoint(people[0], view.ref)

        assert own is not None
        assert [(p, k.get_secret_value()) for p, k in own.keys] == [
            (1, keys[1]),
            (0, keys[0]),
            (2, keys[2]),
        ]
        assert keys[0] not in repr(own)

    async def test_someone_elses_model_does_not_run(
        self, people: tuple[int, int], rotation: dict[str, Any]
    ) -> None:
        view = await _add(people[0])
        with pytest.raises(ConfigError):
            await chat_model.own_endpoint(people[1], view.ref)

    async def test_a_base_url_that_turned_private_stops_the_run(
        self, people: tuple[int, int], rotation: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        view = await _add(people[0])

        async def private(url: str) -> None:
            raise url_guard.BlockedUrl("resolves to a private or internal address")

        monkeypatch.setattr(url_guard, "check", private)
        with pytest.raises(ModelBlocked, match="private"):
            await chat_model.own_endpoint(people[0], view.ref)

    async def test_a_host_model_has_no_endpoint(self, people: tuple[int, int]) -> None:
        assert await chat_model.own_endpoint(people[0], "host:claude-sonnet-5") is None
