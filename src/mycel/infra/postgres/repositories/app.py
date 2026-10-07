"""Product tables: who is logged in, and what they produced.

The fourth repository and the one that is not a pipeline layer. Split out for the same
reason the others are split by layer — the access rule follows the file: nothing in `etl/`
or `agents/` has any business reading `app.user`, and an import line here makes that
visible.

All SQL for `app` lives here. A row's expiry is *not* one of the rules enforced in SQL —
see `session_by_id` for why the caller decides what "expired" means.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import (
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


@dataclass(frozen=True)
class UserRow:
    """A person, as every layer above this one sees them.

    Carries `password_hash` because `services/auth.py` has to verify against it. Nothing
    else may look: the hash never leaves that module, and never reaches a response model.
    """

    id: int
    email: str
    password_hash: str
    created_at: datetime


@dataclass(frozen=True)
class SessionRow:
    """One logged-in browser."""

    id: str
    user_id: int
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class PasswordResetRow:
    """One outstanding reset link."""

    id: int
    user_id: int
    expires_at: datetime
    used_at: datetime | None


@dataclass(frozen=True)
class GoogleAccountRow:
    """One person's connected Google account.

    Carries the token still encrypted: decrypting is `services/google_oauth.py`'s, and a
    row that travels in the clear is a row that ends up in a log line.
    """

    user_id: int
    email: str
    refresh_token_encrypted: str
    scope: str
    connected_at: datetime


@dataclass(frozen=True, slots=True)
class SyncStateRow:
    """How the last background sync went. All `None` before the first run."""

    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None


@dataclass(frozen=True)
class JiraAccountRow:
    """One person's connected Jira account.

    Carries the token still encrypted, as `GoogleAccountRow` does.
    """

    user_id: int
    account_id: str
    display_name: str
    cloud_id: str
    refresh_token_encrypted: str
    scope: str
    connected_at: datetime


@dataclass(frozen=True)
class ConversationRow:
    """One thread in the sidebar."""

    id: int
    user_id: int
    kind: str
    title: str
    created_at: datetime
    pinned_at: datetime | None = None


@dataclass(frozen=True)
class TurnRow:
    """One question and what came back, as kept."""

    id: int
    conversation_id: int
    job_id: str
    question: str
    status: str
    answer: str | None
    error: str | None
    spent_usd: Decimal | None
    #: The tool calls this turn made, as the stream sent them. `None` for a turn that ran
    #: before batch 037, and for one that failed.
    steps: list[Any] | None
    created_at: datetime


class AppRepository:
    """Reads and writes `app`, on a session someone else owns.

    Takes the session rather than opening one, so a caller can put several calls in a
    single transaction — registering a user and opening their first session is one.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- users ---------------------------------------------------------------

    async def create_user(self, email: str, password_hash: str) -> UserRow:
        """Add a person. Raises `IntegrityError` if the email is taken.

        The uniqueness check is the constraint, not a prior `SELECT`: two registrations
        racing on the same address both pass a check and only one passes the index.
        """
        user = User(email=email, password_hash=password_hash)
        self._session.add(user)
        await self._session.flush()
        return _user(user)

    async def user_by_email(self, email: str) -> UserRow | None:
        """Find someone by the address they log in with."""
        row = await self._session.scalar(select(User).where(User.email == email))
        return _user(row) if row else None

    async def user_by_id(self, user_id: int) -> UserRow | None:
        """Find someone by id."""
        row = await self._session.scalar(select(User).where(User.id == user_id))
        return _user(row) if row else None

    async def set_password_hash(self, user_id: int, password_hash: str) -> None:
        """Replace a stored hash — for a rehash onto newer cost parameters."""
        await self._session.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )

    # -- sessions ------------------------------------------------------------

    async def create_session(self, token: str, user_id: int, expires_at: datetime) -> SessionRow:
        """Open a session under a token the caller generated.

        The token arrives already made: generating it is a security decision, and it
        belongs next to the rest of them in `services/auth.py`, not in the SQL.
        """
        row = Session(id=token, user_id=user_id, expires_at=expires_at)
        self._session.add(row)
        await self._session.flush()
        return _session(row)

    async def session_by_id(self, token: str) -> SessionRow | None:
        """The session a cookie names, expired or not.

        Deliberately does not filter on `expires_at`. An expired row and a missing one are
        the same answer to a caller, but they are not the same thing to a sweeper, and a
        repository that hides rows cannot be used to clean them up.
        """
        row = await self._session.scalar(select(Session).where(Session.id == token))
        return _session(row) if row else None

    async def touch_session(self, token: str, at: datetime) -> None:
        """Record that the session was used. Best-effort: a missing row is not an error."""
        await self._session.execute(
            update(Session).where(Session.id == token).values(last_seen_at=at)
        )

    async def delete_session(self, token: str) -> None:
        """Log out. The row goes, and with it any way to use the cookie again."""
        await self._session.execute(delete(Session).where(Session.id == token))

    async def projects_for(self, user_id: int) -> frozenset[str]:
        """Which projects this person has been granted. Absent means none, not all."""
        rows = await self._session.scalars(
            select(Membership.project).where(Membership.user_id == user_id)
        )
        return frozenset(rows)

    async def replace_projects(self, user_id: int, projects: Iterable[str]) -> None:
        """Make this person's grants exactly `projects`, which came from Jira.

        Replaced, never merged: a project they lost in Jira must leave here too, and a
        merge would only ever add.
        """
        await self._session.execute(delete(Membership).where(Membership.user_id == user_id))
        rows = [{"user_id": user_id, "project": p} for p in sorted(set(projects))]
        if rows:
            await self._session.execute(insert(Membership).values(rows))

    async def jira_connected_users(self) -> list[int]:
        """Everyone with a Jira grant, whose access a sync refreshes."""
        rows = await self._session.scalars(
            select(JiraAccount.user_id).order_by(JiraAccount.user_id)
        )
        return list(rows)

    async def upsert_google_account(
        self, user_id: int, email: str, refresh_token_encrypted: str, scope: str
    ) -> None:
        """Attach a Google account, replacing whatever this person had connected before.

        Upsert rather than insert: a second consent is the same person reconnecting, and two
        live grants for one user is two answers to "whose calendar" with no way to choose.
        """
        stmt = insert(GoogleAccount).values(
            user_id=user_id,
            email=email,
            refresh_token_encrypted=refresh_token_encrypted,
            scope=scope,
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[GoogleAccount.user_id],
                set_={
                    "email": stmt.excluded.email,
                    "refresh_token_encrypted": stmt.excluded.refresh_token_encrypted,
                    "scope": stmt.excluded.scope,
                    "connected_at": func.now(),
                },
            )
        )

    async def google_account(self, user_id: int) -> GoogleAccountRow | None:
        """What this person connected, or `None`. `None` is a normal answer."""
        row = await self._session.scalar(
            select(GoogleAccount).where(GoogleAccount.user_id == user_id)
        )
        return _google(row) if row else None

    async def delete_google_account(self, user_id: int) -> bool:
        """Disconnect. False when there was nothing to disconnect."""
        result = await self._session.execute(
            delete(GoogleAccount).where(GoogleAccount.user_id == user_id)
        )
        return bool(getattr(result, "rowcount", 0))

    # -- jira accounts -------------------------------------------------------

    async def upsert_jira_account(
        self,
        user_id: int,
        account_id: str,
        display_name: str,
        cloud_id: str,
        refresh_token_encrypted: str,
        scope: str,
    ) -> None:
        """Attach a Jira account, replacing whatever this person had connected before."""
        stmt = insert(JiraAccount).values(
            user_id=user_id,
            account_id=account_id,
            display_name=display_name,
            cloud_id=cloud_id,
            refresh_token_encrypted=refresh_token_encrypted,
            scope=scope,
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[JiraAccount.user_id],
                set_={
                    "account_id": stmt.excluded.account_id,
                    "display_name": stmt.excluded.display_name,
                    "cloud_id": stmt.excluded.cloud_id,
                    "refresh_token_encrypted": stmt.excluded.refresh_token_encrypted,
                    "scope": stmt.excluded.scope,
                    "connected_at": func.now(),
                },
            )
        )

    async def jira_account(self, user_id: int) -> JiraAccountRow | None:
        """What this person connected, or `None`. `None` is a normal answer."""
        row = await self._session.scalar(select(JiraAccount).where(JiraAccount.user_id == user_id))
        return _jira(row) if row else None

    async def jira_account_locked(self, user_id: int) -> JiraAccountRow | None:
        """The row, locked until this transaction ends.

        Atlassian rotates refresh tokens: spending one returns the next, and the old one
        soon stops working. Two processes refreshing at once would both spend the same
        token and one of them would keep the wrong successor. The lock makes them queue.
        """
        row = await self._session.scalar(
            select(JiraAccount).where(JiraAccount.user_id == user_id).with_for_update()
        )
        return _jira(row) if row else None

    async def set_jira_refresh_token(self, user_id: int, sealed: str) -> None:
        """Keep the successor a refresh just returned."""
        await self._session.execute(
            update(JiraAccount)
            .where(JiraAccount.user_id == user_id)
            .values(refresh_token_encrypted=sealed)
        )

    async def sync_state(self) -> SyncStateRow:
        """How the last background sync went. Empty before the first one."""
        row = await self._session.get(SyncState, 1)
        if row is None:
            return SyncStateRow(None, None, None)
        return SyncStateRow(row.last_success_at, row.last_failure_at, row.last_error)

    async def record_sync(self, at: datetime, error: str | None = None) -> None:
        """Stamp one run: a success clears the error, a failure keeps the last success."""
        values: dict[str, object] = (
            {"last_success_at": at, "last_error": None}
            if error is None
            else {"last_failure_at": at, "last_error": error[:2000]}
        )
        stmt = insert(SyncState).values(id=1, **values)
        await self._session.execute(
            stmt.on_conflict_do_update(index_elements=[SyncState.id], set_=values)
        )

    async def delete_jira_account(self, user_id: int) -> bool:
        """Disconnect. False when there was nothing to disconnect.

        Their project access goes with it: it came from Jira on this token, and with no
        token there is nothing to keep it true.
        """
        await self._session.execute(delete(Membership).where(Membership.user_id == user_id))
        result = await self._session.execute(
            delete(JiraAccount).where(JiraAccount.user_id == user_id)
        )
        return bool(getattr(result, "rowcount", 0))

    async def delete_sessions_for(self, user_id: int, keep: str | None = None) -> int:
        """Drop one person's sessions, optionally sparing the one asking.

        A password change has to end every other session: the point of changing it is that
        someone else may know the old one, and a session already open does not care what
        the password is now.
        """
        query = delete(Session).where(Session.user_id == user_id)
        if keep is not None:
            query = query.where(Session.id != keep)
        result = await self._session.execute(query)
        return int(getattr(result, "rowcount", 0) or 0)

    # -- password resets -----------------------------------------------------

    async def create_password_reset(
        self, user_id: int, token_hash: str, expires_at: datetime
    ) -> None:
        """Record an outstanding reset. The hash arrives already made — hashing is a
        security decision and lives with the rest of them."""
        self._session.add(
            PasswordReset(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        )
        await self._session.flush()

    async def password_reset_by_hash(self, token_hash: str) -> PasswordResetRow | None:
        """The reset a link names, spent or expired or not. The caller decides what counts
        as usable, for the same reason `session_by_id` does."""
        row = await self._session.scalar(
            select(PasswordReset).where(PasswordReset.token_hash == token_hash)
        )
        return _reset(row) if row else None

    async def spend_password_reset(self, reset_id: int, at: datetime) -> int:
        """Mark a reset used, but only if it has not been. Returns how many rows changed,
        which is how two clicks racing each other end with one winner."""
        result = await self._session.execute(
            update(PasswordReset)
            .where(PasswordReset.id == reset_id, PasswordReset.used_at.is_(None))
            .values(used_at=at)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def delete_expired_sessions(self, now: datetime) -> int:
        """Sweep. Nothing depends on it running — expiry is checked on read."""
        result = await self._session.execute(delete(Session).where(Session.expires_at < now))
        return int(getattr(result, "rowcount", 0) or 0)

    # -- conversations -------------------------------------------------------

    async def create_conversation(self, user_id: int, kind: str, title: str) -> ConversationRow:
        """Start a thread."""
        row = Conversation(user_id=user_id, kind=kind, title=title)
        self._session.add(row)
        await self._session.flush()
        return _conversation(row)

    async def conversations_for(
        self, user_id: int, kind: str | None = None, limit: int = 50
    ) -> list[ConversationRow]:
        """One person's sidebar, most recently spoken to first.

        Ordered by the newest turn, not by when the thread was opened. A thread you went
        back to this morning is the one you are working in, and ordering by `created_at`
        buries it under every thread opened since — which is the opposite of what a
        history is for.

        `COALESCE` because a thread with no turns still has to sort: it was opened and the
        worker never wrote a row, and its own `created_at` is the only time it has.

        `updated_at` rather than `created_at`: a turn row is written when the question is
        queued and written again when the run ends, and it is the ending people watch for.
        Ordering on the first write leaves a thread sitting where it was while its answer
        lands somewhere down the list.
        """
        spoke = (
            select(Turn.conversation_id, func.max(Turn.updated_at).label("at"))
            .group_by(Turn.conversation_id)
            .subquery()
        )
        query = (
            select(Conversation)
            .outerjoin(spoke, spoke.c.conversation_id == Conversation.id)
            .where(Conversation.user_id == user_id)
        )
        if kind is not None:
            query = query.where(Conversation.kind == kind)
        # Pinned first, newest pin on top; pins never fall off the end of the page.
        rows = await self._session.scalars(
            query.order_by(
                Conversation.pinned_at.desc().nulls_last(),
                func.coalesce(spoke.c.at, Conversation.created_at).desc(),
            ).limit(limit)
        )
        return [_conversation(row) for row in rows]

    async def conversation_by_id(self, conversation_id: int) -> ConversationRow | None:
        """One thread, whoever owns it. The caller checks that it is theirs."""
        row = await self._session.scalar(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        return _conversation(row) if row else None

    async def pin_conversation(self, conversation_id: int, user_id: int, pinned: bool) -> bool:
        """Pin or unpin a thread. Scoped by `user_id` in the WHERE, like the delete."""
        result = await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .values(pinned_at=func.now() if pinned else None)
        )
        return bool(getattr(result, "rowcount", 0))

    async def delete_conversation(self, conversation_id: int, user_id: int) -> bool:
        """Forget a thread, and every run under it.

        `user_id` is in the WHERE rather than checked by the caller: a delete that scopes
        itself cannot be made to delete someone else's row by a caller that forgot. The
        turns go with it through `ON DELETE CASCADE`.
        """
        result = await self._session.execute(
            delete(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        return bool(getattr(result, "rowcount", 0))

    # -- turns ---------------------------------------------------------------

    async def upsert_turn(
        self,
        conversation_id: int,
        job_id: str,
        question: str,
        status: str,
        answer: str | None = None,
        error: str | None = None,
        spent_usd: Decimal | None = None,
        steps: list[Any] | None = None,
    ) -> None:
        """Write a turn's state, replacing whatever that job id last said.

        Upsert because a job is written twice — once as `queued` when it is enqueued and
        again when it finishes — and a third time if the broker redelivers it.

        `updated_at` is set by hand. The model declares `onupdate`, but that is an ORM hook
        and this is a Core `INSERT ... ON CONFLICT`, which never runs it — the column would
        keep the moment the job was queued, and the sidebar orders on it.
        """
        stmt = insert(Turn).values(
            conversation_id=conversation_id,
            job_id=job_id,
            question=question,
            status=status,
            answer=answer,
            error=error,
            spent_usd=spent_usd,
            steps=steps,
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_turn_job_id",
                set_={
                    "status": stmt.excluded.status,
                    "answer": stmt.excluded.answer,
                    "error": stmt.excluded.error,
                    "spent_usd": stmt.excluded.spent_usd,
                    # Coalesced, not overwritten: a redelivery that ends in failure must
                    # not wipe the steps a successful earlier attempt already wrote.
                    "steps": func.coalesce(stmt.excluded.steps, Turn.steps),
                    "updated_at": func.now(),
                },
            )
        )

    async def turn_by_job_id(self, job_id: str) -> TurnRow | None:
        """What a job produced, however long ago — this is the record Redis is not."""
        row = await self._session.scalar(select(Turn).where(Turn.job_id == job_id))
        return _turn(row) if row else None

    async def turns_for_conversation(self, conversation_id: int) -> list[TurnRow]:
        """Every turn in a thread, oldest first."""
        rows = await self._session.scalars(
            select(Turn).where(Turn.conversation_id == conversation_id).order_by(Turn.created_at)
        )
        return [_turn(row) for row in rows]


def _user(row: User) -> UserRow:
    return UserRow(
        id=row.id, email=row.email, password_hash=row.password_hash, created_at=row.created_at
    )


def _session(row: Session) -> SessionRow:
    return SessionRow(
        id=row.id,
        user_id=row.user_id,
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_seen_at=row.last_seen_at,
    )


def _reset(row: PasswordReset) -> PasswordResetRow:
    return PasswordResetRow(
        id=row.id, user_id=row.user_id, expires_at=row.expires_at, used_at=row.used_at
    )


def _google(row: GoogleAccount) -> GoogleAccountRow:
    return GoogleAccountRow(
        user_id=row.user_id,
        email=row.email,
        refresh_token_encrypted=row.refresh_token_encrypted,
        scope=row.scope,
        connected_at=row.connected_at,
    )


def _jira(row: JiraAccount) -> JiraAccountRow:
    return JiraAccountRow(
        user_id=row.user_id,
        account_id=row.account_id,
        display_name=row.display_name,
        cloud_id=row.cloud_id,
        refresh_token_encrypted=row.refresh_token_encrypted,
        scope=row.scope,
        connected_at=row.connected_at,
    )


def _conversation(row: Conversation) -> ConversationRow:
    return ConversationRow(
        id=row.id,
        user_id=row.user_id,
        kind=row.kind,
        title=row.title,
        created_at=row.created_at,
        pinned_at=row.pinned_at,
    )


def _turn(row: Turn) -> TurnRow:
    return TurnRow(
        id=row.id,
        conversation_id=row.conversation_id,
        job_id=row.job_id,
        question=row.question,
        status=row.status,
        answer=row.answer,
        error=row.error,
        spent_usd=row.spent_usd,
        steps=row.steps,
        created_at=row.created_at,
    )
