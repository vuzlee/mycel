"""Run etl/checks/ after every transform step.

Missing columns, unexpected nulls, row counts off beyond the threshold — raise, so the
pipeline stops instead of writing to the layer above. That layer is silver: the checks run
on the normalised rows, before the first write, so a bad batch leaves silver and gold alike
untouched. Providers change schema without warning all the time; without checks, gold
breaks silently and the agent confidently reports wrong numbers.
"""

from collections.abc import Sequence

from mycel.core.logging import get_logger
from mycel.etl.checks.work import CheckFailed, check_items, check_worklogs
from mycel.infra.postgres.repositories.gold import WorkItemRow, WorklogRow

log = get_logger(__name__)

#: Reasons quoted in the exception. The rest are in the log line; an error message that is
#: five hundred lines long is one nobody reads.
QUOTED = 5


def check_work(items: Sequence[WorkItemRow], worklogs: Sequence[WorklogRow]) -> None:
    """Raise unless every row is fit for the layer above.

    Raising rather than dropping the bad rows: a silently shorter batch is how a dashboard
    ends up quietly wrong, and a stopped sync is the cheap failure of the two — bronze
    still holds everything, so a fixed transform replays it.
    """
    reasons = check_items(items) + check_worklogs(worklogs)
    if not reasons:
        return

    total = len(items) + len(worklogs)
    log.error("rows failed checks", extra={"failed": len(reasons), "of": total})
    raise CheckFailed(f"{len(reasons)} of {total} rows rejected: " + "; ".join(reasons[:QUOTED]))
