/** A cited passage, with a link to the original. A PDF opens at the cited page. */

import { useEffect, useState } from "react";
import { fetchPassage, fetchSourceUrl, type Passage, type SourceRef } from "../../api";
import { Modal } from "../Modal";

export function SourcePanel({ source, onClose }: { source: SourceRef; onClose: () => void }) {
  const [passage, setPassage] = useState<Passage | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    void fetchPassage(source.chunk_id).then(setPassage, (e: Error) => setFailure(e.message));
  }, [source.chunk_id]);

  const open = async (): Promise<void> => {
    const url = await fetchSourceUrl(source.document_id);
    const isPdf = source.mime === "application/pdf";
    window.open(isPdf && source.page ? `${url}#page=${source.page}` : url, "_blank", "noopener");
  };

  const where = [source.page ? `page ${source.page}` : null, source.section || null]
    .filter(Boolean)
    .join(" · ");

  return (
    <Modal title={`[${source.label}] ${source.filename}`} lede={where || undefined} onClose={onClose}>
      {failure && <p className="nb-error">{failure}</p>}
      {passage === null && !failure && <p className="empty">Loading…</p>}
      {passage && <pre className="nb-passage">{passage.text}</pre>}
      <button className="primary" onClick={() => void open()}>
        Open the original
      </button>
    </Modal>
  );
}
