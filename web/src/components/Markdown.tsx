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

const CITE = /\s?\[c(\d+)\]/g;

interface Props {
  body: string;
  /** Turns `[cN]` markers into small numbered links. */
  onCite?: (label: string) => void;
}

export function Markdown({ body, onCite }: Props) {
  const components = onCite
    ? {
        ...COMPONENTS,
        a: ({ href, children }: { href?: string; children?: React.ReactNode }) =>
          href?.startsWith("#cite-") ? (
            <button className="cite" onClick={() => onCite(href.slice(6))}>
              [{children}]
            </button>
          ) : (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
      }
    : COMPONENTS;
  const text = onCite ? body.replace(CITE, (_, n) => `[${n}](#cite-c${n})`) : body;
  return (
    <div className="prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
