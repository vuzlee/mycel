/**
 * The kept answer, for a turn whose stream is over.
 *
 * Since batch 033 the answer is markdown the model writes as free text, so it arrives on
 * the stream as `text` events and `Thread` has already rendered it in place, between the
 * tool calls that produced it. Rendering it again here would print it twice — so the body
 * is shown only when the stream carried none: a run reopened from a link, or one whose
 * events expired out of Redis.
 *
 * The spend is shown either way. It is never on the stream; only the result endpoint and
 * the kept row know it.
 */

import type { ChatResult } from "../api";
import { Markdown } from "./Markdown";

interface Props {
  result: ChatResult;
  /** True when the stream already showed this answer. */
  streamed?: boolean;
}

export function Answer({ result, streamed }: Props) {
  if (!result.answer && !result.spent_usd) return null;

  return (
    <section className="answer">
      {result.answer && !streamed && <Markdown body={result.answer} />}
      {result.spent_usd && <p className="spend">${result.spent_usd}</p>}
    </section>
  );
}
