/** The turns of this conversation that happened before the one being watched. */

import type { Turn } from "../api";
import { buildConversation } from "../lib/buildConversation";
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
              <Steps items={buildConversation(turn.steps)} />
            </div>
          )}
          {turn.status === "done" && turn.answer ? (
            <Answer
              result={{
                job_id: turn.job_id,
                status: "done",
                answer: turn.answer,
                spent_usd: turn.spent_usd,
                sources: [],
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
