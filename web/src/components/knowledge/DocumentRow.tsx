/** One document in the Knowledge list: type badge, name, status line, controls. */

import type { DocumentRow as Row } from "../../api";
import { Mycelium, Pencil, Trash } from "../icons";

const REASONS: Record<string, string> = {
  no_text: "no text found — scanned PDFs are not supported yet",
  too_many_pages: "more than 100 pages",
  unreadable: "the file could not be read",
  timeout: "processing took too long",
  error: "processing failed",
};

export function kindOf(doc: Row): "pdf" | "docx" | "md" {
  if (doc.mime.includes("pdf")) return "pdf";
  if (doc.mime.includes("word") || doc.filename.toLowerCase().endsWith(".docx")) return "docx";
  return "md";
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

interface Props {
  doc: Row;
  onView: (doc: Row) => void;
  onToggle: (doc: Row) => void;
  onAsk: (doc: Row) => void;
  onRename: (doc: Row) => void;
  onDelete: (doc: Row) => void;
}

export function DocumentItem({ doc, onView, onToggle, onAsk, onRename, onDelete }: Props) {
  const kind = kindOf(doc);
  const ready = doc.status === "ready";
  return (
    <li data-enabled={doc.enabled} data-status={doc.status}>
      <span className="kb-kind" data-kind={kind} aria-hidden>
        {kind}
      </span>
      <div className="kb-name">
        <button className="kb-open" title="Open the original" onClick={() => onView(doc)}>
          {doc.filename}
        </button>
        <small>
          <Status doc={doc} />
          {doc.pages ? ` · ${doc.pages} pages` : ""} · {bytes(doc.size)}
        </small>
      </div>
      <span className="kb-actions">
        {ready && doc.enabled && (
          <button className="kb-ask" title="Ask about this document" onClick={() => onAsk(doc)}>
            <Mycelium size={13} />
            Ask
          </button>
        )}
        <button
          className="kb-icon"
          aria-label={`Rename ${doc.filename}`}
          title="Rename"
          onClick={() => onRename(doc)}
        >
          <Pencil />
        </button>
        <button
          className="kb-icon danger"
          aria-label={`Delete ${doc.filename}`}
          title="Delete"
          onClick={() => onDelete(doc)}
        >
          <Trash />
        </button>
      </span>
      {ready && (
        <label
          className="kb-switch"
          title={doc.enabled ? "Used in answers" : "Hidden from answers"}
        >
          <input
            type="checkbox"
            checked={doc.enabled}
            onChange={() => onToggle(doc)}
            aria-label={`Use ${doc.filename} in answers`}
          />
          <span />
        </label>
      )}
    </li>
  );
}

function Status({ doc }: { doc: Row }) {
  if (doc.status === "ready") return <>{doc.enabled ? "in answers" : "hidden from answers"}</>;
  if (doc.status === "failed") {
    return (
      <span className="kb-failed">failed: {REASONS[doc.fail_reason ?? ""] ?? doc.fail_reason}</span>
    );
  }
  return (
    <span className="kb-working">
      <Mycelium size={13} className="grow" />{" "}
      <span className="breathe">{doc.status === "uploaded" ? "queued" : "processing"}</span>
    </span>
  );
}
