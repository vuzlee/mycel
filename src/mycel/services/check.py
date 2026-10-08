"""Run etl/checks/ after every transform step."""

from collections.abc import Sequence

from mycel.core.logging import get_logger
from mycel.etl.checks.work import CheckFailed, check_items, check_worklogs
from mycel.infra.postgres.repositories.gold import WorkItemRow, WorklogRow

log = get_logger(__name__)

#: Reasons quoted in the exception.
QUOTED = 5


def check_work(items: Sequence[WorkItemRow], worklogs: Sequence[WorklogRow]) -> None:
    """Raise unless every row is fit for the layer above."""
    reasons = check_items(items) + check_worklogs(worklogs)
    if not reasons:
        return

    total = len(items) + len(worklogs)
    log.error("rows failed checks", extra={"failed": len(reasons), "of": total})
    raise CheckFailed(f"{len(reasons)} of {total} rows rejected: " + "; ".join(reasons[:QUOTED]))
