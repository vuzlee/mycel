/** Markdown, rendered the one way everywhere it appears. */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** A table is wider than the prose it sits in, so it gets its own scroller rather than
 *  widening the conversation or wrapping every cell to reading width. */
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
