/**
 * Notebooks: pick one, drop documents in, ask it. Three panes on a wide screen,
 * stacked on a narrow one. The notebook lives in the URL so a notebook is a link.
 *
 * Status is polled every few seconds only while a document is queued or processing.
 */

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Unauthorized,
  createNotebook,
  deleteNotebook,
  fetchDocuments,
  fetchNotebooks,
  type DocumentRow,
  type NotebookRow,
  type SourceRef,
} from "../api";
import { useAuth } from "../auth";
import { Shell } from "../components/Shell";
import { Plus, Trash } from "../components/icons";
import { AskPane } from "../components/notebook/AskPane";
import { Documents } from "../components/notebook/Documents";
import { SourcePanel } from "../components/notebook/SourcePanel";

const POLL_MS = 3000;

export function Notebooks() {
  const { forget } = useAuth();
  const [params, setParams] = useSearchParams();
  const [notebooks, setNotebooks] = useState<NotebookRow[] | null>(null);
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [source, setSource] = useState<SourceRef | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");

  const selected = Number(params.get("notebook")) || null;
  const current = notebooks?.find((n) => n.id === selected) ?? null;
  const busy = documents.some((d) => d.status === "uploaded" || d.status === "parsing");
  const usable = documents.some((d) => d.status === "ready" && d.enabled);

  const fail = useCallback(
    (failure: unknown) => {
      if (failure instanceof Unauthorized) forget();
      else setError((failure as Error).message);
    },
    [forget],
  );

  const loadNotebooks = useCallback(() => {
    void fetchNotebooks().then((found) => {
      setNotebooks(found);
      const first = found[0];
      if (selected === null && first) setParams({ notebook: String(first.id) }, { replace: true });
    }, fail);
  }, [fail, selected, setParams]);

  const loadDocuments = useCallback(() => {
    if (selected === null) return;
    void fetchDocuments(selected).then(setDocuments, fail);
  }, [fail, selected]);

  useEffect(loadNotebooks, [loadNotebooks]);
  useEffect(loadDocuments, [loadDocuments]);

  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(loadDocuments, POLL_MS);
    return () => clearInterval(timer);
  }, [busy, loadDocuments]);

  const create = async (): Promise<void> => {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      const made = await createNotebook(trimmed);
      setName("");
      setNotebooks((all) => [...(all ?? []), made]);
      setParams({ notebook: String(made.id) });
    } catch (failure) {
      fail(failure);
    }
  };

  const remove = async (notebook: NotebookRow): Promise<void> => {
    if (!window.confirm(`Delete "${notebook.name}" and every document in it?`)) return;
    try {
      await deleteNotebook(notebook.id);
      setParams({});
      setDocuments([]);
      loadNotebooks();
    } catch (failure) {
      fail(failure);
    }
  };

  return (
    <Shell>
      <div className="page notebooks">
        <aside className="nb-picker">
          <h2 className="label">Notebooks</h2>
          <ol>
            {notebooks?.map((n) => (
              <li key={n.id}>
                <button
                  aria-current={n.id === selected}
                  onClick={() => setParams({ notebook: String(n.id) })}
                  title={n.name}
                >
                  {n.name}
                </button>
                <button
                  className="drop"
                  aria-label={`Delete ${n.name}`}
                  title="Delete notebook"
                  onClick={() => void remove(n)}
                >
                  <Trash />
                </button>
              </li>
            ))}
          </ol>
          <form
            className="nb-new"
            onSubmit={(event) => {
              event.preventDefault();
              void create();
            }}
          >
            <input
              value={name}
              maxLength={120}
              placeholder="New notebook"
              onChange={(event) => setName(event.target.value)}
              aria-label="New notebook name"
            />
            <button className="icon-button" type="submit" aria-label="Create notebook" disabled={!name.trim()}>
              <Plus />
            </button>
          </form>
        </aside>

        {error && (
          <p className="nb-error nb-banner" role="alert">
            {error}
          </p>
        )}

        {current === null ? (
          <p className="empty nb-none">
            {notebooks?.length === 0 ? "Create a notebook to start." : "Pick a notebook."}
          </p>
        ) : (
          <>
            <div className="nb-head">
              <h1>{current.name}</h1>
            </div>
            <Documents notebookId={current.id} documents={documents} onChange={loadDocuments} />
            <AskPane
              notebookId={current.id}
              busy={busy}
              empty={!usable}
              onSource={setSource}
            />
          </>
        )}
      </div>
      {source && <SourcePanel source={source} onClose={() => setSource(null)} />}
    </Shell>
  );
}
