"""One own model behind several keys: a key out of quota or rejected hands over to the next.

Every inner model is the same endpoint and model id, so this is not a fallback: the answer
always comes from the model the person picked. Only quota and auth failures move on; any
other failure is the model's own and is raised as it is.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.wrapper import WrapperModel

from mycel.agents.core.exceptions import key_rejected

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage, ModelResponse
    from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
    from pydantic_ai.settings import ModelSettings

#: Statuses where another key of the same model can succeed.
ROTATE_ON = (401, 402, 403, 429)

#: Called with the position of a key that failed and the HTTP status it failed with.
OnFailure = Callable[[int, int, str], Awaitable[None]]


def _rotates(exc: ModelHTTPError) -> bool:
    return exc.status_code in ROTATE_ON or key_rejected(exc.status_code, exc.body)


class RotatingModel(WrapperModel):
    """Tries `(position, model)` pairs in order; the last failure is raised if all fail."""

    def __init__(self, keyed: "Sequence[tuple[int, Model]]", on_failure: OnFailure) -> None:
        super().__init__(keyed[0][1])
        self._keyed = list(keyed)
        self._on_failure = on_failure

    async def request(
        self,
        messages: "list[ModelMessage]",
        model_settings: "ModelSettings | None",
        model_request_parameters: "ModelRequestParameters",
    ) -> "ModelResponse":
        last: ModelHTTPError | None = None
        for position, model in self._keyed:
            try:
                return await model.request(messages, model_settings, model_request_parameters)
            except ModelHTTPError as exc:
                if not _rotates(exc):
                    raise
                await self._on_failure(position, exc.status_code, str(exc.body or exc))
                last = exc
        assert last is not None
        raise last

    @asynccontextmanager
    async def request_stream(
        self,
        messages: "list[ModelMessage]",
        model_settings: "ModelSettings | None",
        model_request_parameters: "ModelRequestParameters",
        run_context: Any = None,
    ) -> "AsyncIterator[StreamedResponse]":
        # Only a failure before the first chunk moves on: once text has gone out, another
        # key would start the answer over, so a failure past that point is raised as it is.
        last: ModelHTTPError | None = None
        for position, model in self._keyed:
            opened = False
            try:
                async with model.request_stream(
                    messages, model_settings, model_request_parameters, run_context
                ) as stream:
                    opened = True
                    yield stream
                    return
            except ModelHTTPError as exc:
                if opened or not _rotates(exc):
                    raise
                await self._on_failure(position, exc.status_code, str(exc.body or exc))
                last = exc
        assert last is not None
        raise last
