"""Who is making a request, as every layer sees them."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    """What `Depends(current_user)` hands a route and a job hands its agents."""

    id: int
    email: str
