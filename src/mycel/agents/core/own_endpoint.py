"""An own model as one run sees it: endpoint, model id and the keys unsealed for this run.

Built per job and dropped with it. The keys live here as `SecretStr` and reach the client
only; `__repr__` never shows them, so a logged deps object leaks nothing.
"""

from dataclasses import dataclass, field

from pydantic import SecretStr


@dataclass(frozen=True)
class OwnEndpoint:
    #: The `own_model` row id, for rotation state.
    model_id: int
    label: str
    api_base: str
    #: What the endpoint calls the model.
    endpoint_model: str
    #: `(position, key)`, in the order this run tries them.
    keys: tuple[tuple[int, SecretStr], ...] = field(repr=False)
