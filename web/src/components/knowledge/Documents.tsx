/**
 * The user's documents, in a side panel: drop files in, watch them get ready, switch them
 * off, rename, delete. The list itself is live from `useDocuments`; nothing here polls.
 */

import { useEffect, useRef, useState } from "react";
import {
  MAX_UPLOAD_BYTES,
  deleteDocument,
  renameDocument,
  setDocumentEnabled,
  uploadDocument,
  type DocumentRow,
} from "../../api";
import { Close, Mycelium, Spinner, Trash, Upload } from "../icons";

const ACCEPT = ".pdf,.docx,.md,.markdown";

const REASONS: Record<string, string> = {
  no_text: "no text found — scanned PDFs are not supported yet",
  too_many_pages: "more than 100 pages",
  unreadable: "the file could not be read",
  timeout: "processing took too long",
  error: "processing failed",
};

/** Upload files, refusing anything over 2 MB before it is sent. Returns the errors. */
export async function sendFiles(files: FileList | File[]): Promise<string[]> {
  const errors: string[] = [];
  for (const file of Array.from(files)) {
    if (file.size > MAX_UPLOAD_BYTES) {
      errors.push(`${file.name}: files are limited to 2 MB.`);
      continue;
    }
    try {
      await uploadDocument(file);
    } catch (failure) {
      errors.push(`${file.name}: ${(failure as Error).message}`);
    }
  }
  return errors;
}

interface Props {
  open: boolean;
  documents: DocumentRow[];
  onClose: () => void;
}

const WIDTH_KEY = "mycel.kb-width";
const MIN_WIDTH = 280;
const MAX_WIDTH = 640;

/** The panel's width lives in `--kb-w` on the root, so the shell's grid column follows it. */
function setWidth(px: number): void {
  const width = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, px));
  document.documentElement.style.setProperty("--kb-w", `${width}px`);
  try {
    localStorage.setItem(WIDTH_KEY, String(width));
  } catch {
    /* a remembered width is a convenience */
  }
}

/** Drag the left edge to resize; the slide transition is off while dragging. */
function useResize(panel: React.RefObject<HTMLElement>) {
  useEffect(() => {
    try {
      const saved = Number(localStorage.getItem(WIDTH_KEY));
      if (saved) setWidth(saved);
    } catch {
      /* default width */
    }
  }, []);

  return (event: React.PointerEvent): void => {
    event.preventDefault();
    const root = document.documentElement;
    root.dataset.kbDrag = "true";
    const move = (e: PointerEvent): void => setWidth(window.innerWidth - e.clientX);
    const stop = (): void => {
      delete root.dataset.kbDrag;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    panel.current?.focus();
  };
}

export function Documents({ open, documents, onClose }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const panel = useRef<HTMLElement>(null);
  const resize = useResize(panel);

  // Closed, it stays mounted so it can slide out; inert keeps it out of the tab order.
  useEffect(() => {
    panel.current?.toggleAttribute("inert", !open);
  }, [open]);
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(0);

  const send = async (files: FileList | File[]): Promise<void> => {
    setError(null);
    setSending((n) => n + 1);
    try {
      const errors = await sendFiles(files);
      if (errors.length) setError(errors.join(" "));
    } finally {
      setSending((n) => n - 1);
    }
  };

  const rename = async (doc: DocumentRow): Promise<void> => {
    const next = window.prompt("Rename document", doc.filename)?.trim();
    if (!next || next === doc.filename) return;
    try {
      await renameDocument(doc.id, next);
    } catch (failure) {
      setError((failure as Error).message);
    }
  };

  const toggle = async (doc: DocumentRow): Promise<void> => {
    try {
      await setDocumentEnabled(doc.id, !doc.enabled);
    } catch (failure) {
      setError((failure as Error).message);
    }
  };

  const drop = async (doc: DocumentRow): Promise<void> => {
    if (!window.confirm(`Delete ${doc.filename}? This cannot be undone.`)) return;
    try {
      await deleteDocument(doc.id);
    } catch (failure) {
      setError((failure as Error).message);
    }
  };

  return (
    <aside
      ref={panel}
      className="kb-panel"
      data-open={open}
      aria-label="Your documents"
      tabIndex={-1}
    >
      <div
        className="kb-resize"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize documents"
        onPointerDown={resize}
      />
      <header>
        <h2>Knowledge</h2>
        <button className="icon-button" onClick={onClose} aria-label="Close documents">
          <Close />
        </button>
      </header>
      <button
        className="nb-drop"
        data-over={over}
        onClick={() => input.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          void send(event.dataTransfer.files);
        }}
      >
        {sending > 0 ? <Spinner size={14} /> : <Upload size={16} />}
        <span>
          <b>Drop PDF, DOCX or Markdown</b>
          <small>or click to choose · 2 MB each · English</small>
        </span>
      </button>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(event) => {
          if (event.target.files) void send(event.target.files);
          event.target.value = "";
        }}
      />

      {error && <p className="nb-error" role="alert">{error}</p>}

      {documents.length === 0 ? (
        <p className="empty">No documents yet.</p>
      ) : (
        <ul className="nb-list">
          {documents.map((doc) => (
            <li key={doc.id} data-enabled={doc.enabled}>
              <div className="nb-name">
                <button
                  className="nb-rename"
                  title="Rename"
                  onClick={() => void rename(doc)}
                >
                  {doc.filename}
                </button>
                <small>
                  <Status doc={doc} />
                  {doc.pages ? ` · ${doc.pages} pages` : ""}
                </small>
              </div>
              {doc.status === "ready" && (
                <label className="nb-switch" title={doc.enabled ? "Searched" : "Hidden from answers"}>
                  <input
                    type="checkbox"
                    checked={doc.enabled}
                    onChange={() => void toggle(doc)}
                    aria-label={`Use ${doc.filename} in answers`}
                  />
                  <span />
                </label>
              )}
              <button
                className="drop"
                aria-label={`Delete ${doc.filename}`}
                title="Delete"
                onClick={() => void drop(doc)}
              >
                <Trash />
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

function Status({ doc }: { doc: DocumentRow }) {
  if (doc.status === "ready") return <>{doc.enabled ? "ready" : "hidden"}</>;
  if (doc.status === "failed") {
    return <span className="nb-failed">failed: {REASONS[doc.fail_reason ?? ""] ?? doc.fail_reason}</span>;
  }
  return (
    <span className="nb-working">
      <Mycelium size={13} className="grow" />{" "}
      <span className="breathe">{doc.status === "uploaded" ? "queued" : "processing"}</span>
    </span>
  );
}
