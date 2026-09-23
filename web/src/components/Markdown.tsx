/**
 * Markdown, rendered the one way everywhere it appears.
 *
 * The orchestrator has answered in markdown since batch 033, so this renders both the
 * text arriving on the stream and the kept answer of a finished turn. GFM is on for
 * tables: a list of tickets with an assignee and a due date is what most answers are,
 * and a pipe table is how a model writes one.
 *
 * Streaming means this is called on half-written markdown — a table with one row of its
 * header, a link with no closing bracket. `react-markdown` renders what parses and shows
 * the rest as the text it currently is, which is the readable failure.
 */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** A table is wider than the prose it sits in, so it gets its own scroller rather than
 *  widening the thread or wrapping every cell to reading width. */
const COMPONENTS = {
  table: ({ children }: { children?: React.ReactNode }) => (
    <div className="table-scroll">
      <table>{children}</table>
    </div>
  ),
};

export function Markdown({ body }: { body: string }) {
  return (
    <div className="prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {body}
      </ReactMarkdown>
    </div>
  );
}
