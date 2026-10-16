/** Small in-app dialogs that replace the browser's confirm() and prompt(). */

import { useEffect, useRef, useState } from "react";

interface ShellProps {
  title: string;
  onCancel: () => void;
  children: React.ReactNode;
}

function Card({ title, onCancel, children }: ShellProps) {
  const cancel = useRef(onCancel);
  cancel.current = onCancel;
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const key = (event: KeyboardEvent): void => {
      if (event.key === "Escape") cancel.current();
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      before?.focus();
    };
  }, []);

  return (
    <div className="scrim asking" data-open onClick={onCancel}>
      <div
        className="ask-card"
        role="dialog"
        aria-modal
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

interface ConfirmProps {
  title: string;
  body: React.ReactNode;
  action: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function Confirm({ title, body, action, danger, onConfirm, onCancel }: ConfirmProps) {
  return (
    <Card title={title} onCancel={onCancel}>
      <p>{body}</p>
      <div className="choices">
        <button onClick={onCancel}>Cancel</button>
        <button className={danger ? "primary danger" : "primary"} autoFocus onClick={onConfirm}>
          {action}
        </button>
      </div>
    </Card>
  );
}

interface RenameProps {
  title: string;
  value: string;
  onSave: (next: string) => void;
  onCancel: () => void;
}

export function Rename({ title, value, onSave, onCancel }: RenameProps) {
  const [draft, setDraft] = useState(value);
  const next = draft.trim();
  return (
    <Card title={title} onCancel={onCancel}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!next) return;
          if (next === value) onCancel();
          else onSave(next);
        }}
      >
        <input
          className="ask-field"
          aria-label="New name"
          value={draft}
          maxLength={200}
          autoFocus
          onFocus={(event) => event.target.select()}
          onChange={(event) => setDraft(event.target.value)}
        />
        <div className="choices">
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={!next}>
            Save
          </button>
        </div>
      </form>
    </Card>
  );
}
