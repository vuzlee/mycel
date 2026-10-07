"""The mapped tables, one module per schema group.

Every model is imported here, so `Base.metadata` holds every table: alembic autogenerates
against it, and a table missing from this file looks to alembic like one to drop.
"""

from mycel.infra.postgres.models.app import (
    Conversation,
    GoogleAccount,
    JiraAccount,
    Membership,
    PasswordReset,
    Session,
    SyncState,
    Turn,
    User,
)
from mycel.infra.postgres.models.base import APP, BRONZE, GOLD, SILVER, Base
from mycel.infra.postgres.models.documents import Chunk, Document
from mycel.infra.postgres.models.gold import WorkItem, Worklog
from mycel.infra.postgres.models.jira import JiraIssue, JiraWorklog, SilverWorkItem, SilverWorklog

__all__ = [
    "APP",
    "BRONZE",
    "GOLD",
    "SILVER",
    "Base",
    "Chunk",
    "Conversation",
    "Document",
    "GoogleAccount",
    "JiraAccount",
    "JiraIssue",
    "JiraWorklog",
    "Membership",
    "PasswordReset",
    "Session",
    "SilverWorkItem",
    "SilverWorklog",
    "SyncState",
    "Turn",
    "User",
    "WorkItem",
    "Worklog",
]
