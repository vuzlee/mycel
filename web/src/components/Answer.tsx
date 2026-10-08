/** The kept answer, for a turn whose stream is over. */

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
      <Markdown
        body={result.answer}
        onCite={
          result.sources.length > 0
            ? (label) => {
                const s = result.sources.find((x) => x.label === label);
                if (s) onSource?.(s);
              }
            : undefined
        }
      />
      {result.sources.length > 0 && (
        <ol className="kb-sources">
          {result.sources.map((s) => (
            <li key={s.label}>
              <button onClick={() => onSource?.(s)}>
                <b>[{s.label.slice(1)}]</b> {s.filename}
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
