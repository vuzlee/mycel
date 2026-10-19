/** Where you are, and everything you have run. */

import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { ConversationSummary } from "../api";
import { useConversations } from "../context/ConversationsContext";
import { Account } from "./Account";
import { ConversationRow } from "./ConversationRow";
import { Confirm } from "./Dialogs";
import {
  Archive,
  Bars,
  Chevron,
  Close,
  Mycelium,
  Notebook,
  PanelLeft,
  Pin,
  Plus,
  Search,
  Sliders,
  Trash,
} from "./icons";

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
  const pinned = live.filter((t) => t.pinned);
  const recent = live.filter((t) => !t.pinned);
  const [picked, setPicked] = useState<Set<number> | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const picking = picked !== null;
  const chosen = all.filter((t) => picked?.has(t.id));
  const toggle = (id: number): void =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  // One verb for the whole pick: if every row already has it, the verb undoes it.
  const bulkPin = (): void => {
    const rows = chosen.filter((t) => !t.archived);
    const to = !rows.every((t) => t.pinned);
    rows.forEach((t) => void pin(t.id, to));
    setPicked(null);
  };
  const bulkArchive = (): void => {
    const to = !chosen.every((t) => t.archived);
    chosen.forEach((t) => void edit(t.id, { archived: to }));
    setPicked(null);
  };
  const bulkDelete = (): void => {
    chosen.forEach((t) => void forget(t.id));
    if (chosen.some((t) => t.job_id !== null && t.job_id === current)) navigate("/");
    setConfirmDelete(false);
    setPicked(null);
  };
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
            <span className="wordmark">Mycel</span>
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

        <div className="conversations">
          {pinned.length > 0 && (
            <>
              <h2 className="label">Pinned</h2>
              <ol>
                {pinned.map((conversation) => (
                  <ConversationRow
                    selection={picked}
                    onPick={toggle}
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
          <section className="archived" data-open={showArchived}>
            <button
              type="button"
              className="archived-toggle"
              aria-expanded={showArchived}
              onClick={() => setShowArchived((on) => !on)}
            >
              <Archive />
              Archived
              {archived.length > 0 && <span className="count">{archived.length}</span>}
              <Chevron className="archived-chevron" />
            </button>
            {showArchived && archived.length === 0 && <p className="empty">Nothing archived.</p>}
            {showArchived && archived.length > 0 && (
              <ol>
                {archived.map((conversation) => (
                  <ConversationRow
                    selection={picked}
                    onPick={toggle}
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
          </section>
          <div className="recent-head">
            <h2 className="label">Recent</h2>
            <button
              className="icon-button"
              aria-label="Select conversations"
              aria-pressed={picking}
              title="Select"
              onClick={() => setPicked((p) => (p === null ? new Set() : null))}
            >
              <Sliders />
            </button>
          </div>
          {recent.length === 0 && pinned.length === 0 ? (
            <p className="empty">
              {needle ? "No conversation matches." : "Runs you start appear here, ready to reopen."}
            </p>
          ) : (
            <ol>
              {recent.map((conversation) => (
                <ConversationRow
                  selection={picked}
                  onPick={toggle}
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

        {picking && (
          <div className="pick-bar">
            <span>{chosen.length} selected</span>
            <button
              className="icon-button"
              title="Pin / unpin"
              disabled={!chosen.length}
              onClick={bulkPin}
            >
              <Pin />
            </button>
            <button
              className="icon-button"
              title="Archive / unarchive"
              disabled={!chosen.length}
              onClick={bulkArchive}
            >
              <Archive />
            </button>
            <button
              className="icon-button danger"
              title="Delete"
              disabled={!chosen.length}
              onClick={() => setConfirmDelete(true)}
            >
              <Trash />
            </button>
            <button onClick={() => setPicked(null)}>Cancel</button>
          </div>
        )}
        {confirmDelete && (
          <Confirm
            title={`Delete ${chosen.length} conversations?`}
            body="They and every answer in them will be gone for good."
            action="Delete"
            danger
            onConfirm={bulkDelete}
            onCancel={() => setConfirmDelete(false)}
          />
        )}

        {/* The same menu the home page has, in the same shape: profile, settings, help,
            sign out. One component, so the account is never somewhere else. */}
        <Account where="rail" />
      </aside>
    </>
  );
}
