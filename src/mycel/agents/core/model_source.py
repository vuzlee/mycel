"""Which model a run calls: one object that names it, prices it and opens it.

`GatewayModel` is a model behind the gateway; `OwnModel` is one a person added, with keys that
rotate, are redacted while the run holds them, and clients closed when it ends.
"""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from mycel.agents.core.model_builder import build_model, build_own_model
from mycel.agents.core.own_endpoint import OwnEndpoint
from mycel.agents.core.settings import AgentSettings
from mycel.core import redact
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.redis import key_rotation
from mycel.llm.budget import own_price, price_usd
from mycel.llm.model_spec import resolve
from mycel.llm.quota import cooldown_seconds

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.usage import RunUsage

log = get_logger(__name__)


class ModelSource(Protocol):
    #: For logs and metrics.
    @property
    def name(self) -> str: ...

    #: For the person: what an error message calls the model.
    @property
    def label(self) -> str: ...

    def price(self, usage: "RunUsage") -> Decimal | None: ...

    def open(self, cfg: AgentSettings, job_id: str) -> AbstractAsyncContextManager["Model"]: ...


@dataclass(frozen=True, slots=True)
class GatewayModel:
    spec: str

    @property
    def name(self) -> str:
        return self.spec

    @property
    def label(self) -> str:
        return self.spec

    def price(self, usage: "RunUsage") -> Decimal | None:
        return price_usd(get_settings().model_prices_usd, resolve(self.spec).name, usage)

    @asynccontextmanager
    async def open(self, cfg: AgentSettings, job_id: str) -> AsyncIterator["Model"]:
        yield build_model(self.spec, cfg)


@dataclass(frozen=True, slots=True)
class OwnModel:
    endpoint: OwnEndpoint

    @property
    def name(self) -> str:
        return f"own:{self.endpoint.endpoint_model}"

    @property
    def label(self) -> str:
        return self.endpoint.label

    def price(self, usage: "RunUsage") -> Decimal | None:
        return own_price(self.endpoint.endpoint_model, self.endpoint.api_base, usage)

    @asynccontextmanager
    async def open(self, cfg: AgentSettings, job_id: str) -> AsyncIterator["Model"]:
        """Clients built for this run only, keys held for redaction, closed after."""
        own = self.endpoint

        async def set_aside(position: int, status: int, error: str) -> None:
            log.warning(
                "own model key set aside",
                extra={
                    "job_id": job_id,
                    "own_model": own.model_id,
                    "key": position,
                    "status": status,
                },
            )
            await key_rotation.cool(own.model_id, position, cooldown_seconds(status, error))

        model, clients = build_own_model(own, cfg, set_aside)
        try:
            with redact.holding(*(key.get_secret_value() for _, key in own.keys)):
                yield model
        finally:
            for client in clients:
                await client.close()
