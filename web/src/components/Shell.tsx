/**
 * The frame every signed-in page sits in: the rail on the left, a header strip, a
 * scrolling body. The pages differ in what goes in the body, not in this.
 *
 * The header strip carries nothing but the button that reveals the rail on a narrow
 * screen. A run's id, its clock and its cost were all there; each was a fact about the
 * machine, offered to someone who came to read an answer.
 */

import { useState } from "react";
import { ArrowDown, Menu } from "./icons";
import { Sidebar } from "./Sidebar";

interface Props {
  /** Job id of the run on screen, so the rail can mark its row. */
  current?: string | null;
  /** Passed to the scrolling body. Nothing scrolls it on its own — see `useFollow`. */
  scrollRef?: (node: HTMLDivElement | null) => void;
  /** Offered only while the bottom is off screen: with no auto-scroll, work happening
   *  below the fold is otherwise invisible. */
  jump?: () => void;
  children: React.ReactNode;
  /** Below the scroll area, outside it: the composer, where a page has one. */
  footer?: React.ReactNode;
  /** The map of a long thread, floating in the gutter beside the prose. Inside `.main`
   *  rather than beside it: it is positioned against the body it maps, and it takes no
   *  column — a column would shove the thread off centre at the second question. */
  aside?: React.ReactNode;
}

export function Shell({ current = null, scrollRef, jump, children, footer, aside }: Props) {
  const [menu, setMenu] = useState(false);

  return (
    <div className="shell">
      <Sidebar current={current} open={menu} onClose={() => setMenu(false)} />
      <main className="main">
        <header>
          <button
            className="icon-button reveal"
            onClick={() => setMenu(true)}
            aria-label="Show menu"
          >
            <Menu />
          </button>
        </header>
        <div className="scroll" ref={scrollRef}>
          {children}
        </div>
        {jump && (
          <button className="jump" onClick={jump} aria-label="Scroll to the newest">
            <ArrowDown />
          </button>
        )}
        {aside}
        {footer}
      </main>
    </div>
  );
}
