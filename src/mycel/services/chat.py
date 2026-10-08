"""Queue a chat question with what the worker needs to answer it."""

from mycel.agents.core.chips import Chip
from mycel.infra.postgres.repositories.conversations import (
    ConversationRepository,
    ConversationRow,
    TurnRow,
)
from mycel.infra.postgres.session import session_scope
from mycel.services.enqueue import enqueue_chat

#: How much of a question becomes the conversation's title in the sidebar.
TITLE_CHARS = 80

#: How many earlier turns a follow-up carries.
HISTORY_TURNS = 6

#: And a ceiling in characters, because one long answer outweighs six short turns.
HISTORY_CHARS = 6000

#: What the rewriter reads for a follow-up's search: "it" points at something recent.
REWRITE_QUESTIONS = 3
REWRITE_ANSWER_CHARS = 500


class ConversationNotFound(Exception):
    """The conversation asked for is not this person's, or not there."""


async def request_chat(
    user_id: int,
    question: str,
    conversation_id: int | None = None,
    chips: list[str] | None = None,
) -> tuple[str, int]:
    """Queue a question; returns the job id and its conversation (new if none is given)."""
    async with session_scope() as session:
        repo = ConversationRepository(session)
        if conversation_id is None:
            conversation = await repo.create_conversation(
                user_id, kind="chat", title=question[:TITLE_CHARS]
            )
            turns = []
        else:
            conversation = await _conversation_of(repo, user_id, conversation_id)
            turns = await repo.turns_for_conversation(conversation.id)

        previous = context = ""
        if chips is not None and Chip.KNOWLEDGE in chips:
            previous, context = _last_question(turns), _rewrite_context(turns)
        job_id = await enqueue_chat(
            question,
            conversation.id,
            _recall(turns),
            user_id=user_id,
            chips=chips,
            previous=previous,
            context=context,
        )
        await repo.upsert_turn(conversation.id, job_id, question, status="queued")
    return job_id, conversation.id


def _last_question(turns: list[TurnRow]) -> str:
    """The question before this one, for a follow-up's search. Empty on a first question."""
    return turns[-1].question if turns else ""


def _rewrite_context(turns: list[TurnRow]) -> str:
    """What the rewriter reads: the last few questions and the head of the last answer."""
    if not turns:
        return ""
    asked = "\n".join(f"- {t.question}" for t in turns[-REWRITE_QUESTIONS:])
    said = [t.answer for t in turns if t.status == "done" and t.answer]
    text = f"Earlier questions:\n{asked}"
    if said:
        text += f"\n\nStart of the last answer:\n{said[-1][:REWRITE_ANSWER_CHARS]}"
    return text


async def _conversation_of(
    repo: ConversationRepository, user_id: int, conversation_id: int
) -> ConversationRow:
    """The conversation a follow-up names, once it is established that it is this person's."""
    conversation = await repo.conversation_by_id(conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise ConversationNotFound(conversation_id)
    return conversation


def _recall(turns: list[TurnRow]) -> str:
    """Earlier turns of a conversation, as text for the prompt."""
    done = [turn for turn in turns if turn.status == "done" and turn.answer]
    if not done:
        return ""

    kept: list[str] = []
    spent = 0
    # Newest first, so the ceiling drops the oldest turns.
    for turn in reversed(done[-HISTORY_TURNS:]):
        block = f"Q: {turn.question}\nA: {turn.answer}"
        if kept and spent + len(block) > HISTORY_CHARS:
            break
        kept.append(block)
        spent += len(block)

    kept.reverse()
    dropped = len(done) - len(kept)
    head = "Earlier in this conversation"
    if dropped:
        head += f" ({dropped} earlier turn(s) omitted)"
    return f"{head}:\n\n" + "\n\n".join(kept)


async def find_turn(job_id: str) -> TurnRow | None:
    """The kept record of a run, whatever Redis has since forgotten."""
    async with session_scope() as session:
        return await ConversationRepository(session).turn_by_job_id(job_id)
