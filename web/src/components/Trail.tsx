/** Everything a run did on its way to the answer, folded into one line. */

import type { Item, ToolItem } from "../lib/buildConversation";
import { labelFor } from "../lib/toolLabel";
import { Chevron, Mycelium, Spinner } from "./icons";
import { Json } from "./Json";
import { Markdown } from "./Markdown";

interface Props {
  items: Item[];
  live: boolean;
  gaps?: Map<number, number>;
}

export function Trail({ items, live, gaps }: Props) {
  if (items.length === 0 && !live) return null;
  const steps = countTools(items);
  const now = live ? deepestPending(items) : null;

  return (
    <details className="trail" data-live={live}>
      <summary>
        <Mycelium className={live ? "grow" : "rest"} size={15} />
        <b>{live ? "Myceling" : "Mycelled"}</b>
        <span className="trail-meta">
          {live
            ? now
              ? labelFor(now.tool)
              : null
            : steps > 0
              ? `${steps} step${steps === 1 ? "" : "s"}`
              : "no tools"}
        </span>
        {items.length > 0 && <Chevron className="chevron" />}
      </summary>
      {items.length > 0 && <ol className="trail-steps">{rows(items, gaps)}</ol>}
    </details>
  );
}

function rows(items: Item[], gaps?: Map<number, number>): React.ReactNode {
  return items.map((item) => {
    const lost = gaps?.get(item.seq);
    return (
      <li key={`${item.kind}-${item.seq}`}>
        {lost && <p className="gap">— {lost} event(s) lost —</p>}
        <Row item={item} gaps={gaps} />
      </li>
    );
  });
}

function Row({ item, gaps }: { item: Item; gaps?: Map<number, number> }) {
  switch (item.kind) {
    case "mark":
      return <p className="gap">{item.label}</p>;
    case "thinking":
      return (
        <details className="step">
          <summary>
            <span className="dot think" />
            <span className="what">Thought</span>
            <span className="peek">{item.body.trim()}</span>
          </summary>
          <div className="step-body thought">{item.body.trim()}</div>
        </details>
      );
    case "text":
      return (
        <details className="step">
          <summary>
            <span className="dot say" />
            <span className="what">{item.agent}</span>
            <span className="peek">{item.body.trim()}</span>
          </summary>
          <div className="step-body">
            <Markdown body={item.body} />
          </div>
        </details>
      );
    case "tool":
      return <ToolRow item={item} gaps={gaps} />;
  }
}

function ToolRow({ item, gaps }: { item: ToolItem; gaps?: Map<number, number> }) {
  const pending = item.result === null;
  return (
    <>
      <details className="step">
        <summary>
          <span className="dot tool" />
          <span className="what">{labelFor(item.tool)}</span>
          <span className="peek">{item.args && item.args !== "{}" ? item.args : ""}</span>
          {pending ? <Spinner className="spin" size={11} /> : <span className="done">✓</span>}
        </summary>
        <div className="step-body">
          <span className="label">{item.tool} · arguments</span>
          <Json text={item.args || "{}"} />
          {!pending && (
            <>
              <span className="label">Result</span>
              <Json text={item.result ?? ""} />
            </>
          )}
        </div>
      </details>
      {item.children.length > 0 && (
        <ol className="trail-steps nested">{rows(item.children, gaps)}</ol>
      )}
    </>
  );
}

function countTools(items: Item[]): number {
  return items.reduce(
    (n, item) => n + (item.kind === "tool" ? 1 + countTools(item.children) : 0),
    0,
  );
}

/** The innermost unfinished call: the outer ones are only waiting on this one. */
function deepestPending(items: Item[]): ToolItem | null {
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item?.kind !== "tool" || item.result !== null) continue;
    return deepestPending(item.children) ?? item;
  }
  return null;
}
