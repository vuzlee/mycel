"""What one answered turn used: the line under the answer."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TurnUsage:
    model_ref: str
    tokens_in: int
    tokens_out: int
    #: From the worker starting the attempt to the answer; queue wait excluded.
    duration_ms: int
