/**
 * The turns of this thread that happened before the one being watched.
 *
 * Read from `app.turn`, not from the stream: a stream belongs to one run, and these runs
 * are over. Since batch 037 a turn keeps its tool calls in the shape the stream sent them,
 * so they build the same tree and render through the same `Steps`. Reasoning is not kept
 * — it is worth watching live and not worth storing — so a replayed turn shows what it
 * called and what came back, and none of the thinking in between.
 */

import type { Turn } from "../api";
import { buildThread } from "../thread";
import { Answer } from "./Answer";
import { Steps } from "./Steps";
import { anchorFor } from "./Topics";

interface Props {
  turns: Turn[];
}

export function PastTurns({ turns }: Props) {
  return (
    <>
      {turns.map((turn) => (
        <div key={turn.job_id} className="past" id={anchorFor(turn.job_id)}>
          <div className="turn user">
            <div className="bubble">{turn.question}</div>
          </div>
          {turn.steps && turn.steps.length > 0 && (
            <div className="turn items">
              <Steps items={buildThread(turn.steps)} />
            </div>
          )}
          {turn.status === "done" && turn.answer ? (
            <Answer
              result={{
                job_id: turn.job_id,
                status: "done",
                answer: turn.answer,
                spent_usd: turn.spent_usd,
                error: null,
                conversation_id: null,
                question: turn.question,
              }}
            />
          ) : (
            <p className="failure">{turn.error ?? "This turn did not finish."}</p>
          )}
        </div>
      ))}
    </>
  );
}
