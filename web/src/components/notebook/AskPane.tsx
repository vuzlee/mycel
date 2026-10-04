/** Ask the open notebook. Locked while a document is processing, like the API. */

import { useEffect, useState } from "react";
import { askNotebook, fetchAsk, fetchAskQuota, type AskState, type SourceRef } from "../../api";
import { Markdown } from "../Markdown";
import { ArrowUp, Spinner } from "../icons";

const MAX_CHARS = 500;
const POLL_MS = 1500;

interface Exchange {
  question: string;
  state: AskState | null;
  error: string | null;
}

interface Props {
  notebookId: number;
  busy: boolean;
  empty: boolean;
  onSource: (source: SourceRef) => void;
}

export function AskPane({ notebookId, busy, empty, onSource }: Props) {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<Exchange[]>([]);
  const [left, setLeft] = useState<number | null>(null);
  const waiting = history.some((x) => x.state === null && x.error === null);

  useEffect(() => {
    setHistory([]);
    void fetchAskQuota().then(setLeft, () => setLeft(null));
  }, [notebookId]);

  const settle = (index: number, patch: Partial<Exchange>): void =>
    setHistory((all) => all.map((x, i) => (i === index ? { ...x, ...patch } : x)));

  const submit = async (): Promise<void> => {
    const text = question.trim();
    if (!text || busy || waiting) return;
    const index = history.length;
    setHistory((all) => [...all, { question: text, state: null, error: null }]);
    setQuestion("");
    try {
      let state = await askNotebook(notebookId, text);
      while (state.status === "queued" || state.status === "running") {
        await new Promise((done) => setTimeout(done, POLL_MS));
        state = await fetchAsk(state.job_id ?? "");
      }
      settle(index, { state });
    } catch (failure) {
      settle(index, { error: (failure as Error).message });
    }
    void fetchAskQuota().then(setLeft, () => undefined);
  };

  const locked = busy ? "Processing documents…" : empty ? "Upload a document first." : null;

  return (
    <section className="nb-ask">
      <div className="nb-answers">
        {history.length === 0 && (
          <p className="empty">Answers come only from this notebook's documents, with sources.</p>
        )}
        {history.map((x, i) => (
          <article key={i}>
            <p className="nb-q">{x.question}</p>
            {x.error && <p className="nb-error">{x.error}</p>}
            {!x.error && x.state === null && (
              <p className="nb-working">
                <Spinner size={12} /> Reading the documents…
              </p>
            )}
            {x.state?.status === "failed" && <p className="nb-error">{x.state.error}</p>}
            {x.state?.status === "done" && (
              <>
                <Markdown body={x.state.answer ?? ""} />
                {x.state.sources.length > 0 && (
                  <ol className="nb-sources">
                    {x.state.sources.map((s) => (
                      <li key={s.label}>
                        <button onClick={() => onSource(s)}>
                          <b>[{s.label}]</b> {s.filename}
                          {s.page ? `, page ${s.page}` : ""}
                          {s.section ? <small> · {s.section}</small> : null}
                        </button>
                      </li>
                    ))}
                  </ol>
                )}
                {x.state.cached && <small className="nb-meta">from cache · no quota used</small>}
              </>
            )}
          </article>
        ))}
      </div>

      <form
        className="nb-composer"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <textarea
          value={question}
          maxLength={MAX_CHARS}
          disabled={locked !== null}
          placeholder={locked ?? "Ask this notebook…"}
          rows={2}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <div className="nb-composer-foot">
          <small>
            {left === null ? "" : `${left} question${left === 1 ? "" : "s"} left today`}
          </small>
          <button
            className="primary"
            type="submit"
            disabled={locked !== null || waiting || !question.trim()}
            aria-label="Ask"
          >
            <ArrowUp />
          </button>
        </div>
      </form>
    </section>
  );
}
