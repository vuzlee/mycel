"""Silver to gold: one source's clean rows become the shape the product reads.

Both functions are the identity today, and the module still earns its name. Silver
answers to the source and gold answers to the question the product asks; with Jira as the
only source those two shapes coincide, so promotion is a copy. It stops being one the
moment a second tracker lands and its fields have to be reconciled, or the moment gold
grows something derived that silver has no business holding.

A step with no name is a step that gets inlined into its caller and then forgotten, and
the next person reads a two-layer pipeline that the docs call three.

Pure functions, like `checks/`: nothing in `etl/` touches a session.
"""

from mycel.infra.postgres.repositories.gold import WorkItemRow, WorklogRow


def to_gold_item(row: WorkItemRow) -> WorkItemRow:
    """One work item, as gold stores it."""
    return row


def to_gold_worklog(row: WorklogRow) -> WorklogRow:
    """One logged entry, as gold stores it."""
    return row
