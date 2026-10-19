/** One conversation in the rail, with a ⋯ menu: rename, pin, archive, delete. */

import { useEffect, useRef, useState } from "react";
import type { ConversationSummary } from "../api";
import { Confirm, Rename } from "./Dialogs";
import { Archive, Bubble, Check, Dots, Pencil, Pin, Trash } from "./icons";

interface Props {
  conversation: ConversationSummary;
  current: string | null;
  onOpen: (conversation: ConversationSummary) => void;
  onPin: (id: number, pinned: boolean) => Promise<void>;
  onEdit: (id: number, change: { title?: string; archived?: boolean }) => Promise<void>;
  onDrop: (conversation: ConversationSummary) => void;
  /** Set while the rail is picking several: a click ticks the row instead of opening it. */
  selection?: Set<number> | null;
  onPick?: (id: number) => void;
}

export function ConversationRow({
  conversation,
  current,
  onOpen,
  onPin,
  onEdit,
  onDrop,
  selection = null,
  onPick,
}: Props) {
  const picking = selection !== null;
  const picked = selection?.has(conversation.id) ?? false;
  const [menu, setMenu] = useState(false);
  const [dialog, setDialog] = useState<"rename" | "delete" | null>(null);
  const root = useRef<HTMLLIElement>(null);

  useEffect(() => {
    if (!menu) return;
    const close = (event: MouseEvent): void => {
      if (!root.current?.contains(event.target as Node)) setMenu(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menu]);

  const act = (run: () => void) => () => {
    setMenu(false);
    run();
  };

  return (
    <li ref={root} data-menu={menu}>
      <button
        aria-current={conversation.job_id !== null && conversation.job_id === current}
        title={conversation.title}
        aria-pressed={picking ? picked : undefined}
        onClick={() => (picking ? onPick?.(conversation.id) : onOpen(conversation))}
      >
        {picking ? (
          <span className="tick" data-on={picked}>
            {picked && <Check size={10} />}
          </span>
        ) : (
          <Bubble size={13} />
        )}
        <span className="title">{conversation.title}</span>
        {/* A queued run nobody is working on is exactly what someone needs to see. */}
        {conversation.status !== null && conversation.status !== "done" && (
          <span className="state">{conversation.status}</span>
        )}
      </button>
      {!picking && (
        <button
          className="more"
          aria-label={`Options for ${conversation.title}`}
          aria-haspopup="menu"
          aria-expanded={menu}
          onClick={() => setMenu((open) => !open)}
        >
          <Dots />
        </button>
      )}
      {menu && (
        <div className="row-menu" role="menu">
          <button role="menuitem" onClick={act(() => setDialog("rename"))}>
            <Pencil />
            Rename
          </button>
          {!conversation.archived && (
            <button
              role="menuitem"
              onClick={act(() => void onPin(conversation.id, !conversation.pinned))}
            >
              <Pin />
              {conversation.pinned ? "Unpin" : "Pin"}
            </button>
          )}
          <button
            role="menuitem"
            onClick={act(() => void onEdit(conversation.id, { archived: !conversation.archived }))}
          >
            <Archive />
            {conversation.archived ? "Unarchive" : "Archive"}
          </button>
          <button role="menuitem" className="danger" onClick={act(() => setDialog("delete"))}>
            <Trash />
            Delete
          </button>
        </div>
      )}
      {dialog === "rename" && (
        <Rename
          title="Rename conversation"
          value={conversation.title}
          onSave={(title) => {
            setDialog(null);
            void onEdit(conversation.id, { title });
          }}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog === "delete" && (
        <Confirm
          title="Delete conversation?"
          body={
            <>
              <b>{conversation.title}</b> and every answer in it will be gone for good.
            </>
          }
          action="Delete"
          danger
          onConfirm={() => {
            setDialog(null);
            onDrop(conversation);
          }}
          onCancel={() => setDialog(null)}
        />
      )}
    </li>
  );
}
