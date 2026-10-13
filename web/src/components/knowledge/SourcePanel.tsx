/** A cited source, with the quote marked; the original is one click away. */

import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { fetchPassage, fetchSourceUrl, type Passage, type SourceRef } from "../../api";
import { Modal } from "../Modal";

const PdfPage = lazy(() => import("./PdfPage").then((m) => ({ default: m.PdfPage })));

/** The passage, with the first case-insensitive occurrence of the quote marked. */
function Marked({ text, quote }: { text: string; quote: string }) {
  const at = quote ? text.toLowerCase().indexOf(quote.toLowerCase()) : -1;
  if (at < 0) return <pre className="kb-passage">{text}</pre>;
  return (
    <pre className="kb-passage">
      {text.slice(0, at)}
      <mark>{text.slice(at, at + quote.length)}</mark>
      {text.slice(at + quote.length)}
    </pre>
  );
}

export function SourcePanel({ source, onClose }: { source: SourceRef; onClose: () => void }) {
  const isPdf = source.mime === "application/pdf" && source.page !== null;
  const quote = source.quote ?? "";

  // Keyed by the source, so a fast second click can never show the first one's text.
  const fetched = useQuery<{ url: string | null; passage: Passage | null }>({
    queryKey: ["source", isPdf ? "pdf" : "chunk", isPdf ? source.document_id : source.chunk_id],
    queryFn: async () =>
      isPdf
        ? { url: await fetchSourceUrl(source.document_id), passage: null }
        : { url: null, passage: await fetchPassage(source.chunk_id) },
  });
  const url = fetched.data?.url ?? null;
  const passage = fetched.data?.passage ?? null;
  const failure = fetched.error?.message ?? null;

  const open = async (): Promise<void> => {
    const original = url ?? (await fetchSourceUrl(source.document_id));
    window.open(isPdf ? `${original}#page=${source.page}` : original, "_blank", "noopener");
  };

  const pages =
    source.page && source.page_end && source.page_end !== source.page
      ? `pages ${source.page}–${source.page_end}`
      : source.page
        ? `page ${source.page}`
        : null;
  const where = [pages, source.section || null].filter(Boolean).join(" · ");
  const loading = fetched.isPending;

  return (
    <Modal
      title={`[${source.label}] ${source.filename}`}
      lede={where || undefined}
      onClose={onClose}
      wide={isPdf}
    >
      {failure && <p className="kb-error">{failure}</p>}
      {loading && <p className="empty">Loading…</p>}
      {isPdf && url && (
        <Suspense fallback={<p className="empty">Loading…</p>}>
          <PdfPage
            url={url}
            first={source.page!}
            last={source.page_end ?? source.page!}
            quote={quote}
          />
        </Suspense>
      )}
      {passage && <Marked text={passage.text} quote={quote} />}
      <button className="primary" onClick={() => void open()}>
        Open the original
      </button>
    </Modal>
  );
}
