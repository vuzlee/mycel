/**
 * The kept answer, for a turn whose stream is over.
 *
 * Since batch 033 the answer is markdown the model writes as free text, so it arrives on
 * the stream as `text` events and `Thread` has already rendered it in place, between the
 * tool calls that produced it. Rendering it again here would print it twice — so the body
 * is shown only when the stream carried none: a run reopened from a link, or one whose
 * events expired out of Redis.
 *
 * The cost of the run used to print under it. It is gone: the reader of an answer is not
 * the payer of it, and a figure in dollars under a paragraph invites a judgement about
 * whether the paragraph was worth it. The spend is still recorded on the turn, and the
 * trace is where it belongs.
 */

import type { ChatResult, SourceRef } from "../api";
import { Markdown } from "./Markdown";

interface Props {
  result: ChatResult;
  /** True when the stream already showed this answer. */
  streamed?: boolean;
  /** Opens a cited passage. */
  onSource?: (source: SourceRef) => void;
}

export function Answer({ result, streamed, onSource }: Props) {
  if (!result.answer || streamed) return null;

  return (
    <section className="answer">
      <Markdown body={result.answer} />
      {result.sources.length > 0 && (
        <ol className="nb-sources">
          {result.sources.map((s) => (
            <li key={s.label}>
              <button onClick={() => onSource?.(s)}>
                <b>[{s.label}]</b> {s.filename}
                {s.page ? `, page ${s.page}` : ""}
                {s.section ? <small> · {s.section}</small> : null}
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
