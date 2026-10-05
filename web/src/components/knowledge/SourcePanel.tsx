/**
 * A cited source. A PDF shows the cited page in the app with the quote marked; other files
 * show the passage with the quote marked. The original is one click away either way.
 */

import { lazy, Suspense, useEffect, useState } from "react";
import { fetchPassage, fetchSourceUrl, type Passage, type SourceRef } from "../../api";
import { Modal } from "../Modal";

const PdfPage = lazy(() => import("./PdfPage").then((m) => ({ default: m.PdfPage })));

/** The passage, with the first case-insensitive occurrence of the quote marked. */
function Marked({ text, quote }: { text: string; quote: string }) {
  const at = quote ? text.toLowerCase().indexOf(quote.toLowerCase()) : -1;
  if (at < 0) return <pre className="nb-passage">{text}</pre>;
  return (
    <pre className="nb-passage">
      {text.slice(0, at)}
      <mark>{text.slice(at, at + quote.length)}</mark>
      {text.slice(at + quote.length)}
    </pre>
  );
}

export function SourcePanel({ source, onClose }: { source: SourceRef; onClose: () => void }) {
  const [passage, setPassage] = useState<Passage | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const isPdf = source.mime === "application/pdf" && source.page !== null;
  const quote = source.quote ?? "";

  useEffect(() => {
    const fail = (e: Error): void => setFailure(e.message);
    if (isPdf) void fetchSourceUrl(source.document_id).then(setUrl, fail);
    else void fetchPassage(source.chunk_id).then(setPassage, fail);
  }, [isPdf, source.chunk_id, source.document_id]);

  const open = async (): Promise<void> => {
    const original = url ?? (await fetchSourceUrl(source.document_id));
    window.open(isPdf ? `${original}#page=${source.page}` : original, "_blank", "noopener");
  };

  const where = [source.page ? `page ${source.page}` : null, source.section || null]
    .filter(Boolean)
    .join(" · ");
  const loading = !failure && (isPdf ? url === null : passage === null);

  return (
    <Modal title={`[${source.label}] ${source.filename}`} lede={where || undefined} onClose={onClose}>
      {failure && <p className="nb-error">{failure}</p>}
      {loading && <p className="empty">Loading…</p>}
      {isPdf && url && (
        <Suspense fallback={<p className="empty">Loading…</p>}>
          <PdfPage url={url} page={source.page!} quote={quote} />
        </Suspense>
      )}
      {passage && <Marked text={passage.text} quote={quote} />}
      <button className="primary" onClick={() => void open()}>
        Open the original
      </button>
    </Modal>
  );
}
