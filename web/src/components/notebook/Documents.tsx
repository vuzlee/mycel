/** One notebook's documents: drop files in, watch them get ready, switch them off, delete. */

import { useRef, useState } from "react";
import {
  MAX_UPLOAD_BYTES,
  deleteDocument,
  setDocumentEnabled,
  uploadDocument,
  type DocumentRow,
} from "../../api";
import { Spinner, Trash, Upload } from "../icons";

const ACCEPT = ".pdf,.docx,.md,.markdown";

const REASONS: Record<string, string> = {
  no_text: "no text found — scanned PDFs are not supported yet",
  too_many_pages: "more than 100 pages",
  unreadable: "the file could not be read",
  timeout: "processing took too long",
  error: "processing failed",
};

interface Props {
  notebookId: number;
  documents: DocumentRow[];
  onChange: () => void;
}

export function Documents({ notebookId, documents, onChange }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(0);

  const send = async (files: FileList | File[]): Promise<void> => {
    setError(null);
    for (const file of Array.from(files)) {
      if (file.size > MAX_UPLOAD_BYTES) {
        setError(`${file.name}: files are limited to 2 MB.`);
        continue;
      }
      setSending((n) => n + 1);
      try {
        await uploadDocument(notebookId, file);
      } catch (failure) {
        setError(`${file.name}: ${(failure as Error).message}`);
      } finally {
        setSending((n) => n - 1);
        onChange();
      }
    }
  };

  const toggle = async (doc: DocumentRow): Promise<void> => {
    try {
      await setDocumentEnabled(doc.id, !doc.enabled);
    } catch (failure) {
      setError((failure as Error).message);
    }
    onChange();
  };

  const drop = async (doc: DocumentRow): Promise<void> => {
    if (!window.confirm(`Delete ${doc.filename}? This cannot be undone.`)) return;
    try {
      await deleteDocument(doc.id);
    } catch (failure) {
      setError((failure as Error).message);
    }
    onChange();
  };

  return (
    <section className="nb-docs">
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
                <span title={doc.filename}>{doc.filename}</span>
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
    </section>
  );
}

function Status({ doc }: { doc: DocumentRow }) {
  if (doc.status === "ready") return <>{doc.enabled ? "ready" : "hidden"}</>;
  if (doc.status === "failed") {
    return <span className="nb-failed">failed: {REASONS[doc.fail_reason ?? ""] ?? doc.fail_reason}</span>;
  }
  return (
    <span className="nb-working">
      <Spinner size={10} /> {doc.status === "uploaded" ? "queued" : "processing"}
    </span>
  );
}
