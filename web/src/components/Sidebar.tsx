/**
 * Where you are, and everything you have run.
 *
 * Two destinations above the history and one list below it: a new chat, the board, and
 * every conversation. The board is not a conversation and never appears in that list — it has no
 * history of its own, it is the same screen every time you open it.
 *
 * The history comes from `GET /conversations` now, not `localStorage`: it is the same
 * list on a second machine, which is the whole reason it moved to Postgres.
 *
 * The theme button that used to sit beside the wordmark is gone: a setting belongs in
 * the settings, and a rail header holding a wordmark, a theme and a close reads as three
 * unrelated things at the same rank.
 *
 * Below 760px the rail slides in over the page instead of taking a column, so the
 * history stays reachable on a phone rather than disappearing with the layout.
 */

import { Link, useLocation, useNavigate } from "react-router-dom";
import type { ConversationSummary } from "../api";
import { useConversations } from "../context/ConversationsContext";
import { Account } from "./Account";
import { Bars, Close, Mycelium, Pin, Plus, Trash } from "./icons";

interface Props {
  /** Job id of the run on screen, so its row reads as current. */
  current: string | null;
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ current, open, onClose }: Props) {
  const { conversations, forget, pin } = useConversations();
  const pinned = conversations.filter((t) => t.pinned);
  const recent = conversations.filter((t) => !t.pinned);
  const navigate = useNavigate();
  const { pathname } = useLocation();

  // Every conversation reopens at `/`. There is one page and one kind of conversation, so
  // `kind` is not consulted — the job id is the whole address.
  //
  // `conversation` travels with `job`, though the page could derive it. Deriving it costs a poll:
  // the page reads the conversation off the run, the run has to be fetched, and until it
  // comes back the conversation id is null — which reads as a conversation with no history, so the
  // earlier turns blank out and reappear a second later. The row already knows its own id,
  // so it says it.
  const open_ = (conversation: ConversationSummary): void => {
    navigate(
      conversation.job_id ? `/?job=${conversation.job_id}&conversation=${conversation.id}` : "/",
    );
    onClose();
  };

  // Deleting the conversation on screen leaves the page showing a run that no longer has a
  // home, so it goes back to an empty Ask. Deleting any other one leaves the page alone.
  const drop = (conversation: ConversationSummary): void => {
    void forget(conversation.id);
    if (conversation.job_id !== null && conversation.job_id === current) navigate("/");
  };

  return (
    <>
      <div className="scrim" data-open={open} onClick={onClose} />
      <aside className="rail" data-open={open}>
        <header>
          {/* The wordmark goes home, the way a wordmark does everywhere else. Signed in,
              `/home` is still worth reaching: it is where what this thing does is written
              down, and there is a way straight back from it. */}
          <Link
            className="brand"
            to="/home"
            onClick={onClose}
            title="What Mycel is"
          >
            <span className="mark">
              <Mycelium size={15} />
            </span>
            Mycel
          </Link>
          <button
            className="icon-button shut"
            onClick={onClose}
            aria-label="Close menu"
          >
            <Close />
          </button>
        </header>

        <button
          className="new-run"
          onClick={() => {
            navigate("/");
            onClose();
          }}
        >
          <Plus />
          New chat
        </button>

        {/* The one screen in the app that is not a conversation, so it sits with the
            button that starts one rather than among the conversations below — a board is not a
            thing you have a history of. No project in the link: the page picks the first
            one you may read and writes it into the URL, which is what makes a board a
            link worth keeping once you have picked. */}
        <button
          className="board-link"
          aria-current={pathname === "/dashboard"}
          onClick={() => {
            navigate("/dashboard");
            onClose();
          }}
        >
          <Bars />
          Dashboard
        </button>

        <div className="conversations">
          {pinned.length > 0 && (
            <>
              <h2 className="label">Pinned</h2>
              <ol>
                {pinned.map((conversation) => (
                  <Row
                    key={conversation.id}
                    conversation={conversation}
                    current={current}
                    onOpen={open_}
                    onPin={pin}
                    onDrop={drop}
                  />
                ))}
              </ol>
            </>
          )}
          <h2 className="label">Recent</h2>
          {conversations.length === 0 ? (
            <p className="empty">
              Runs you start appear here, ready to reopen.
            </p>
          ) : (
            <ol>
              {recent.map((conversation) => (
                <Row
                  key={conversation.id}
                  conversation={conversation}
                  current={current}
                  onOpen={open_}
                  onPin={pin}
                  onDrop={drop}
                />
              ))}
            </ol>
          )}
        </div>

        {/* The same menu the home page has, in the same shape: profile, settings, help,
            sign out. One component, so the account is never somewhere else. */}
        <Account where="rail" />
      </aside>
    </>
  );
}

interface RowProps {
  conversation: ConversationSummary;
  current: string | null;
  onOpen: (conversation: ConversationSummary) => void;
  onPin: (id: number, pinned: boolean) => Promise<void>;
  onDrop: (conversation: ConversationSummary) => void;
}

function Row({ conversation, current, onOpen, onPin, onDrop }: RowProps) {
  return (
    <li>
      <button
        aria-current={conversation.job_id !== null && conversation.job_id === current}
        title={conversation.title}
        onClick={() => onOpen(conversation)}
      >
        {conversation.title}
        {/* A conversation the worker never picked up is shown, not hidden: a queued run nobody
            is working on is exactly what someone needs to see. */}
        {conversation.status !== null && conversation.status !== "done" && (
          <span className="state">{conversation.status}</span>
        )}
      </button>
      {/* Hidden until the row is hovered or tabbed to: a delete sitting under every
          title, always lit, is a delete someone hits. */}
      <span className="row-actions">
        <button
          className="pin"
          data-on={conversation.pinned}
          title={conversation.pinned ? "Unpin" : "Pin to the top"}
          aria-label={`${conversation.pinned ? "Unpin" : "Pin"} ${conversation.title}`}
          onClick={() => void onPin(conversation.id, !conversation.pinned)}
        >
          <Pin />
        </button>
        <button
          className="drop"
          title="Forget this conversation"
          aria-label={`Forget ${conversation.title}`}
          onClick={() => onDrop(conversation)}
        >
          <Trash />
        </button>
      </span>
    </li>
  );
}
