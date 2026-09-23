/**
 * The turns of this thread that happened before the one being watched.
 *
 * Read from `app.turn`, not from the stream: a stream belongs to one run, and these runs
 * are over. So a past turn is its question and its answer, and nothing else — the tool
 * calls under it lived in Redis and expired (MYC-41).
 */

import type { Turn } from "../api";
import { Answer } from "./Answer";

interface Props {
  turns: Turn[];
}

export function PastTurns({ turns }: Props) {
  return (
    <>
      {turns.map((turn) => (
        <div key={turn.job_id} className="past">
          <div className="turn user">
            <div className="bubble">{turn.question}</div>
          </div>
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
