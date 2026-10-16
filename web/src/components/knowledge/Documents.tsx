/** The user's documents: upload, watch, toggle, rename, delete. */

import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  MAX_UPLOAD_BYTES,
  deleteDocument,
  fetchSourceUrl,
  updateDocument,
  uploadDocument,
  type DocumentRow,
} from "../../api";
import { Confirm, Rename } from "../Dialogs";
import { Spinner, Upload } from "../icons";
import { DocumentItem } from "./DocumentRow";

const ACCEPT = ".pdf,.docx,.md,.markdown";

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
  documents: DocumentRow[];
  loading: boolean;
  failure: string | null;
  /** Title and lede, laid out beside the upload button. */
  intro: React.ReactNode;
  /** Figures under the header, when there is anything to count. */
  summary?: React.ReactNode;
}

type Sort = "new" | "name" | "size";

export function Documents({ documents, loading, failure, intro, summary }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("new");
  const needle = query.trim().toLowerCase();
  const shown = documents
    .filter((d) => !needle || d.filename.toLowerCase().includes(needle))
    .sort((a, b) =>
      sort === "name"
        ? a.filename.localeCompare(b.filename)
        : sort === "size"
          ? b.size - a.size
          : b.id - a.id,
    );

  // Opens a new chat with the Knowledge source already picked.
  const ask = (doc: DocumentRow): void => {
    navigate(`/?source=knowledge&about=${encodeURIComponent(doc.filename)}`);
  };
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

  const [renaming, setRenaming] = useState<DocumentRow | null>(null);
  const [dropping, setDropping] = useState<DocumentRow | null>(null);

  const rename = async (doc: DocumentRow, next: string): Promise<void> => {
    setRenaming(null);
    try {
      await updateDocument(doc.id, { filename: next });
    } catch (failure) {
      setError((failure as Error).message);
    }
  };

  // The tab opens inside the click; an await first would get it blocked as a popup.
  const view = (doc: DocumentRow): void => {
    const tab = window.open("", "_blank");
    if (!tab) return;
    tab.opener = null;
    void fetchSourceUrl(doc.id).then(
      (url) => tab.location.replace(url),
      (failure: Error) => {
        tab.close();
        setError(failure.message);
      },
    );
  };

  const toggle = async (doc: DocumentRow): Promise<void> => {
    try {
      await updateDocument(doc.id, { enabled: !doc.enabled });
    } catch (failure) {
      setError((failure as Error).message);
    }
  };

  const drop = async (doc: DocumentRow): Promise<void> => {
    setDropping(null);
    try {
      await deleteDocument(doc.id);
    } catch (failure) {
      setError((failure as Error).message);
    }
  };

  return (
    <section
      className="kb-page"
      aria-label="Your documents"
      data-over={over}
      onDragOver={(event) => {
        if (!event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node)) setOver(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        void send(event.dataTransfer.files);
      }}
    >
      <header className="kb-head">
        <div>{intro}</div>
        <button className="kb-upload" onClick={() => input.current?.click()}>
          {sending > 0 ? <Spinner size={14} /> : <Upload size={15} />}
          Upload
        </button>
      </header>
      {summary}
      {!loading && documents.length === 0 && !failure && (
        <button className="kb-drop" data-empty onClick={() => input.current?.click()}>
          <Upload size={22} />
          <span>
            <b>Drop PDF, DOCX or Markdown</b>
            <small>or click to choose · 2 MB each · English</small>
          </span>
        </button>
      )}
      {over && (
        <div className="kb-overlay" aria-hidden>
          <Upload size={26} />
          <b>Drop to add to Knowledge</b>
        </div>
      )}
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

      {error && (
        <p className="kb-error" role="alert">
          {error}
        </p>
      )}

      {failure && (
        <p className="kb-error" role="alert">
          {failure}
        </p>
      )}

      {loading ? (
        <p className="empty">Loading…</p>
      ) : documents.length === 0 ? (
        !failure && (
          <div className="kb-empty">
            <p>
              Upload a handbook, a spec or meeting notes. Pick <b>Knowledge</b> when you ask, and
              answers will quote the passages they used, with a link back to the page.
            </p>
          </div>
        )
      ) : (
        <>
          {documents.length > 10 && (
            <div className="kb-tools">
              <input
                type="search"
                className="kb-search"
                placeholder="Filter documents"
                aria-label="Filter documents"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <select
                className="kb-sort"
                aria-label="Sort"
                value={sort}
                onChange={(event) => setSort(event.target.value as Sort)}
              >
                <option value="new">Newest</option>
                <option value="name">Name</option>
                <option value="size">Largest</option>
              </select>
            </div>
          )}
          <ul className="kb-list">
            {shown.map((doc) => (
              <DocumentItem
                key={doc.id}
                doc={doc}
                onView={view}
                onToggle={(d) => void toggle(d)}
                onAsk={ask}
                onRename={setRenaming}
                onDelete={setDropping}
              />
            ))}
            {shown.length === 0 && <li className="kb-none">No document matches.</li>}
          </ul>
        </>
      )}
      {renaming && (
        <Rename
          title="Rename document"
          value={renaming.filename}
          onSave={(next) => void rename(renaming, next)}
          onCancel={() => setRenaming(null)}
        />
      )}
      {dropping && (
        <Confirm
          title="Delete document?"
          body={
            <>
              <b>{dropping.filename}</b> and everything indexed from it will be removed. This cannot
              be undone.
            </>
          }
          action="Delete"
          danger
          onConfirm={() => void drop(dropping)}
          onCancel={() => setDropping(null)}
        />
      )}
    </section>
  );
}
