"""Which models a person may pick: toggles, default, and what a run falls back to."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.config import HostModel, Settings
from mycel.infra.postgres.repositories.identity import IdentityRepository
from mycel.infra.postgres.repositories.models import ModelPrefRepository
from mycel.services import model_catalog as models
from tests.fakes import needs_postgres

pytestmark = [pytest.mark.anyio, needs_postgres]

A, B = "host:model-a", "host:model-b"


@pytest.fixture
async def user_id(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> int:
    """Two host models, A the default; every service call runs on the test's session."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        yield session
        await session.flush()

    monkeypatch.setattr(models, "session_scope", scope)
    settings = Settings(
        host_models=(
            HostModel(name="model-a", label="A", default=True),
            HostModel(name="model-b", label="B"),
        )
    )
    monkeypatch.setattr(models, "get_settings", lambda: settings)
    return (await IdentityRepository(session).create_user("a@x.com")).id


class TestToggles:
    async def test_a_new_person_has_every_host_model_on(self, user_id: int) -> None:
        found = await models.models_for(user_id)
        assert [(c.ref, c.enabled) for c in found.choices] == [(A, True), (B, True)]
        assert found.default_ref == A

    async def test_turning_one_off(self, user_id: int) -> None:
        found = await models.set_enabled(user_id, B, False)
        assert [c.enabled for c in found.choices] == [True, False]

    async def test_the_last_one_stays_on(self, user_id: int) -> None:
        await models.set_enabled(user_id, B, False)
        with pytest.raises(models.LastModel):
            await models.set_enabled(user_id, A, False)

    async def test_an_unknown_ref_is_refused(self, user_id: int) -> None:
        with pytest.raises(models.UnknownModel):
            await models.set_enabled(user_id, "host:nope", False)

    async def test_turning_the_default_off_moves_the_default(self, user_id: int) -> None:
        found = await models.set_enabled(user_id, A, False)
        assert found.default_ref == B


class TestDefault:
    async def test_a_chosen_default(self, user_id: int) -> None:
        assert (await models.set_default(user_id, B)).default_ref == B

    async def test_a_model_that_is_off_cannot_be_the_default(self, user_id: int) -> None:
        await models.set_enabled(user_id, B, False)
        with pytest.raises(models.UnknownModel):
            await models.set_default(user_id, B)

    async def test_a_forgotten_model_clears_the_default(
        self, user_id: int, session: AsyncSession
    ) -> None:
        await models.set_default(user_id, B)
        await ModelPrefRepository(session).forget(B)
        assert (await ModelPrefRepository(session).toggles_and_default(user_id))[1] is None


class TestOneRoundTrip:
    """Toggles and default come back from one query, the user row joined to its toggles."""

    async def test_nothing_set_is_no_toggles_and_no_default(
        self, user_id: int, session: AsyncSession
    ) -> None:
        assert await ModelPrefRepository(session).toggles_and_default(user_id) == ({}, None)

    async def test_several_toggles_and_a_default_together(
        self, user_id: int, session: AsyncSession
    ) -> None:
        await models.set_enabled(user_id, B, False)
        await models.set_enabled(user_id, A, True)
        await models.set_default(user_id, A)

        found = await ModelPrefRepository(session).toggles_and_default(user_id)
        assert found == ({A: True, B: False}, A)


class TestResolveBeforeARun:
    async def test_no_pick_is_the_default(self, user_id: int) -> None:
        assert await models.resolve(user_id, None) == (A, None)

    async def test_a_usable_pick_is_kept(self, user_id: int) -> None:
        assert await models.resolve(user_id, B) == (B, None)

    async def test_a_pick_turned_off_since_falls_back_with_a_warning(self, user_id: int) -> None:
        await models.set_enabled(user_id, B, False)
        ref, warning = await models.resolve(user_id, B)
        assert ref == A
        assert warning is not None and B in warning

    async def test_a_pick_no_longer_in_config_falls_back(self, user_id: int) -> None:
        ref, warning = await models.resolve(user_id, "host:removed")
        assert ref == A and warning is not None


def test_gateway_name_only_for_listed_host_models() -> None:
    settings = Settings()
    assert models.gateway_name("host:gemini-3.5-flash-lite", settings) == "gemini-3.5-flash-lite"
    assert models.gateway_name("host:not-listed", settings) is None
    assert models.gateway_name("own:3", settings) is None
