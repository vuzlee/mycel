/**
 * A tool's arguments or result, pretty-printed when it is JSON and left alone when not.
 *
 * Results are often prose or a Python repr; only text that parses is re-indented and
 * colored, so nothing a tool returned is ever rewritten into something it did not say.
 */

const TOKEN = /("(?:\\.|[^"\\])*"(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

function indent(raw: string): string | null {
  const text = raw.trim();
  if (!/^[[{]/.test(text)) return null;
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return null;
  }
}

export function Json({ text }: { text: string }) {
  const pretty = indent(text);
  if (pretty === null) return <pre className="raw">{text || "—"}</pre>;

  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of pretty.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    parts.push(pretty.slice(last, at));
    const token = m[0];
    const kind = m[2] ? "key" : token.startsWith('"') ? "str" : /\d/.test(token[0] ?? "") || token[0] === "-" ? "num" : "lit";
    parts.push(
      <span key={at} className={`j-${kind}`}>
        {token}
      </span>,
    );
    last = at + token.length;
  }
  parts.push(pretty.slice(last));
  return <pre className="json">{parts}</pre>;
}
