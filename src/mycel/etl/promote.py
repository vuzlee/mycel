"""Silver to gold; a copy while Jira is the only source."""

from mycel.infra.postgres.repositories.gold import WorkItemRow, WorklogRow


def to_gold_item(row: WorkItemRow) -> WorkItemRow:
    return row


def to_gold_worklog(row: WorklogRow) -> WorklogRow:
    return row
