/** The knowledge base as its own page: the documents answers can draw on. */

import { Documents } from "../components/knowledge/Documents";
import { Shell } from "../components/Shell";
import type { DocumentRow } from "../api";
import { bytes } from "../components/knowledge/DocumentRow";
import { useDocuments } from "../hooks/useDocuments";

function Summary({ documents }: { documents: DocumentRow[] }) {
  const used = documents.filter((d) => d.status === "ready" && d.enabled).length;
  const pages = documents.reduce((n, d) => n + (d.pages ?? 0), 0);
  const size = documents.reduce((n, d) => n + d.size, 0);
  const figures: [string, string][] = [
    [String(documents.length), documents.length === 1 ? "document" : "documents"],
    [String(used), "in answers"],
    [String(pages), "pages"],
    [bytes(size), "stored"],
  ];
  return (
    <dl className="kb-summary">
      {figures.map(([value, label]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function Knowledge() {
  const docs = useDocuments();
  return (
    <Shell>
      <div className="page knowledge">
        <Documents
          documents={docs.documents}
          loading={docs.loading}
          failure={docs.error}
          intro={
            <>
              <h1>Knowledge</h1>
              <p>
                Documents Mycel can cite when you pick the Knowledge source. Turn one off to keep it
                out of answers without deleting it.
              </p>
            </>
          }
          summary={docs.documents.length > 0 && <Summary documents={docs.documents} />}
        />
      </div>
    </Shell>
  );
}
