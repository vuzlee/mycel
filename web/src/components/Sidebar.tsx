/** Where you are, and everything you have run. */

import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { ConversationSummary } from "../api";
import { useConversations } from "../context/ConversationsContext";
import { Account } from "./Account";
import { ConversationRow as Row } from "./ConversationRow";
import { Archive, Bars, Close, Mycelium, Notebook, PanelLeft, Plus, Search } from "./icons";

interface Props {
  /** Job id of the run on screen, so its row reads as current. */
  current: string | null;
  open: boolean;
  onClose: () => void;
  /** Desktop only: fold the rail away. */
  onCollapse: () => void;
}

export function Sidebar({ current, open, onClose, onCollapse }: Props) {
  const { conversations: all, forget, pin, edit } = useConversations();
  const [showArchived, setShowArchived] = useState(false);
  const [query, setQuery] = useState<string | null>(null);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (query !== null) field.current?.focus();
  }, [query !== null]); // eslint-disable-line react-hooks/exhaustive-deps
  const needle = query?.trim().toLowerCase() ?? "";
  const conversations = needle ? all.filter((t) => t.title.toLowerCase().includes(needle)) : all;
  const live = conversations.filter((t) => !t.archived);
  const archived = conversations.filter((t) => t.archived);
  const pinned = showArchived ? [] : live.filter((t) => t.pinned);
  const recent = showArchived ? archived : live.filter((t) => !t.pinned);
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
          <Link className="brand" to="/home" onClick={onClose} title="What Mycel is">
            <span className="mark">
              <Mycelium size={15} />
            </span>
            Mycel
          </Link>
          <div className="rail-tools">
            <button
              className="icon-button"
              aria-label="Search conversations"
              aria-pressed={query !== null}
              title="Search"
              onClick={() => setQuery((q) => (q === null ? "" : null))}
            >
              <Search />
            </button>
            <button
              className="icon-button fold"
              aria-label="Collapse sidebar"
              title="Collapse sidebar"
              onClick={onCollapse}
            >
              <PanelLeft />
            </button>
            <button className="icon-button shut" onClick={onClose} aria-label="Close menu">
              <Close />
            </button>
          </div>
        </header>

        {query !== null && (
          <input
            ref={field}
            className="rail-search"
            type="search"
            placeholder="Search conversations"
            aria-label="Search conversations"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") setQuery(null);
            }}
          />
        )}

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
        <button
          className="board-link"
          aria-current={pathname === "/knowledge"}
          onClick={() => {
            navigate("/knowledge");
            onClose();
          }}
        >
          <Notebook />
          Knowledge
        </button>
        <button
          className="board-link"
          aria-pressed={showArchived}
          onClick={() => setShowArchived((on) => !on)}
        >
          <Archive />
          Archived
          {archived.length > 0 && <span className="count">{archived.length}</span>}
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
                    onEdit={edit}
                    onDrop={drop}
                  />
                ))}
              </ol>
            </>
          )}
          <h2 className="label">{showArchived ? "Archived" : "Recent"}</h2>
          {recent.length === 0 && pinned.length === 0 ? (
            <p className="empty">
              {needle
                ? "No conversation matches."
                : showArchived
                  ? "Nothing archived."
                  : "Runs you start appear here, ready to reopen."}
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
                  onEdit={edit}
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
