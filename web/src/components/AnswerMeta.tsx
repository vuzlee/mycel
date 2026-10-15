/** The line under an answer: copy it, and what it took. A field the turn did not keep is left out. */

import { useState } from "react";
import type { TurnUsage } from "../api";
import { clock, compact, duration, money } from "../lib/usage";
import { Check, Chip, Clock, Coin, Copy, Tokens } from "./icons";

interface Props {
  answer: string;
  usage: TurnUsage;
}

/** An own key pays its own way: shown as an estimate, outside the daily allowance. */
const ownKey = (ref: string | null): boolean => ref?.startsWith("own:") ?? false;
const OWN = "Your own key: an estimate, not counted in the daily allowance";
const HOST = "Counted in the daily allowance";

export function AnswerMeta({ answer, usage }: Props) {
  const [copied, setCopied] = useState(false);
  const copy = (): void => {
    void navigator.clipboard.writeText(answer).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };
  const own = ownKey(usage.model_ref);
  const tokens =
    usage.tokens_in !== null && usage.tokens_out !== null
      ? usage.tokens_in + usage.tokens_out
      : null;
  // Tokens spent at no cost: the model is missing from the price table, not free.
  const unpriced = Number(usage.spent_usd) === 0 && (tokens ?? 0) > 0;

  return (
    <div className="answer-meta">
      <button
        type="button"
        className="icon-button"
        aria-label={copied ? "Copied" : "Copy answer"}
        title={copied ? "Copied" : "Copy"}
        onClick={copy}
      >
        {copied ? <Check /> : <Copy />}
      </button>
      {usage.model_label && (
        <span title={usage.model_ref ?? undefined}>
          <Chip size={13} />
          {usage.model_label}
        </span>
      )}
      {tokens !== null && (
        <span title={`${compact(usage.tokens_in!)} in · ${compact(usage.tokens_out!)} out`}>
          <Tokens />
          {compact(tokens)} tok
        </span>
      )}
      {usage.duration_ms !== null && (
        <span title="Run time, queue wait excluded">
          <Clock />
          {duration(usage.duration_ms)}
        </span>
      )}
      {usage.spent_usd !== null && (
        <span title={unpriced ? "This model has no price on record" : own ? OWN : HOST}>
          <Coin />
          {unpriced ? "no price" : `${own ? "~" : ""}${money(usage.spent_usd)}`}
        </span>
      )}
      {usage.created_at && (
        <time dateTime={usage.created_at} title={new Date(usage.created_at).toLocaleString()}>
          {clock(usage.created_at)}
        </time>
      )}
    </div>
  );
}
