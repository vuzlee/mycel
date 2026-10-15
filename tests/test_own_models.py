"""A person's own models: sealed keys that never come back, owner-only, bounded."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.config import get_settings
from mycel.infra.postgres.models import OwnModelKey
from mycel.infra.postgres.repositories.identity import IdentityRepository
from mycel.infra.postgres.repositories.models import ModelPrefRepository
from mycel.services import models, own_models, tokens, url_guard
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
    a = (await identity.create_user("a@x.com", "x")).id
    b = (await identity.create_user("b@x.com", "x")).id
    return a, b


async def _add(owner: int, keys: list[str] | None = None) -> own_models.OwnModelView:
    return await own_models.add_own(owner, "My Gemini", "gemini-3.6-flash", BASE, keys or [KEY])


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
