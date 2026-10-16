/** Everything a run did on its way to the answer, folded into one line. */

import type { Item, ToolItem } from "../lib/buildConversation";
import { useEffect, useState } from "react";
import { labelFor, resultSummary } from "../lib/toolLabel";
import { duration } from "../lib/usage";
import { Chevron, Mycelium, Spinner } from "./icons";
import { Json } from "./Json";
import { Markdown } from "./Markdown";

interface Props {
  items: Item[];
  live: boolean;
  gaps?: Map<number, number>;
  /** Show the line even with no steps, so every finished turn has one. */
  always?: boolean;
  /** How long the finished run took; while it runs, the line counts up on its own. */
  durationMs?: number | null;
}

export function Trail({ items, live, gaps, always = false, durationMs }: Props) {
  const elapsed = useElapsed(live);
  if (items.length === 0 && !live && !always) return null;
  const steps = countTools(items);
  const now = live ? deepestPending(items) : null;
  const took = durationMs ? ` · ${duration(durationMs)}` : "";

  return (
    <details className="trail" data-live={live}>
      <summary>
        <Mycelium className={live ? "grow" : "rest"} size={15} />
        {live ? <Wave text="Myceling..." /> : <b>Mycelled</b>}
        <span className="trail-meta">
          {live
            ? [now ? labelFor(now.tool, now.args) : null, elapsed >= 1 ? `${elapsed}s` : null]
                .filter(Boolean)
                .join(" · ")
            : `${steps > 0 ? `${steps} step${steps === 1 ? "" : "s"}` : "no tools"}${took}`}
        </span>
        {items.length > 0 && <Chevron className="chevron" />}
      </summary>
      {items.length > 0 && <ol className="trail-steps">{rows(items, live, gaps)}</ol>}
    </details>
  );
}

/** Whole seconds since `live` turned on; 0 when it is off. */
function useElapsed(live: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    setSeconds(0);
    if (!live) return;
    const start = Date.now();
    const tick = setInterval(() => setSeconds(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(tick);
  }, [live]);
  return seconds;
}

/** Each letter brightens in turn; nothing moves, so the line never shifts while it waits. */
function Wave({ text }: { text: string }) {
  return (
    <b className="wave" aria-label={text}>
      {[...text].map((char, i) => (
        <span key={i} aria-hidden style={{ animationDelay: `${i * 0.09}s` }}>
          {char}
        </span>
      ))}
    </b>
  );
}

function rows(items: Item[], live: boolean, gaps?: Map<number, number>): React.ReactNode {
  return items.map((item) => {
    const lost = gaps?.get(item.seq);
    return (
      <li key={`${item.kind}-${item.seq}`}>
        {lost && <p className="gap">— {lost} event(s) lost —</p>}
        <Row item={item} live={live} gaps={gaps} />
      </li>
    );
  });
}

function Row({ item, live, gaps }: { item: Item; live: boolean; gaps?: Map<number, number> }) {
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
      return <ToolRow item={item} live={live} gaps={gaps} />;
  }
}

function ToolRow({
  item,
  live,
  gaps,
}: {
  item: ToolItem;
  live: boolean;
  gaps?: Map<number, number>;
}) {
  // An agent's final answer is never echoed back as a result, so a finished run settles it.
  const pending = live && item.result === null;
  return (
    <>
      <details className="step">
        <summary>
          <span className="dot tool" />
          <span className="what">{labelFor(item.tool, item.args)}</span>
          <span className="peek">{pending ? "" : resultSummary(item.result ?? "")}</span>
          {pending ? <Spinner className="spin" size={11} /> : <span className="done">✓</span>}
        </summary>
        <div className="step-body">
          {/* What went in and came out, as sent: for whoever is debugging, folded away. */}
          <details className="raw-io">
            <summary>Raw</summary>
            <span className="label">{item.tool} · arguments</span>
            <Json text={item.args || "{}"} />
            {!pending && (
              <>
                <span className="label">Result</span>
                <Json text={item.result ?? ""} />
              </>
            )}
          </details>
        </div>
      </details>
      {item.children.length > 0 && (
        <ol className="trail-steps nested">{rows(item.children, live, gaps)}</ol>
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
