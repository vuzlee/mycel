/**
 * The conversation: the question asked, then everything the run did about it.
 *
 * The steps themselves render in `Steps`, which a finished turn reuses.
 */

import type { Item } from "../lib/buildConversation";
import { Steps } from "./Steps";

interface Props {
  /** The id the right-hand map scrolls to for this turn. */
  anchor?: string;
  question: string | null;
  items: Item[];
  gaps: Map<number, number>;
  failure: string | null;
  /** True until an answer or a failure is on screen — not merely until the stream shuts. */
  pending: boolean;
  /** The kept answer. The same text the stream already showed, for a turn
   *  reopened after its stream was over. */
  children?: React.ReactNode;
  /** Earlier turns of the same conversation, already finished. Above the question on screen
   *  because that is the order they were asked in. */
  before?: React.ReactNode;
}

export function Conversation({
  anchor,
  question,
  items,
  gaps,
  failure,
  pending,
  children,
  before,
}: Props) {
  return (
    <div className="conversation">
      {before}
      {/* The turn on screen, as one block. It is one element rather than siblings so CSS can
          give it a floor of a viewport's height — without that floor there is nothing below
          a question just asked, the browser has no room to scroll it up with, and it lands
          a few lines short of the top instead of at it. Once the answer outgrows the screen
          the floor stops applying and the block is just its content. */}
      <div className="live">
        {question !== null && (
          <div className="turn user" id={anchor}>
            <div className="bubble">{question}</div>
          </div>
        )}
        <div className="turn items">
          <Steps items={items} gaps={gaps} live={pending} />
        </div>
        {children}
        {failure && <p className="failure">{failure}</p>}
      </div>
    </div>
  );
}
