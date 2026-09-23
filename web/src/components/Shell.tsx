/**
 * The frame every signed-in page sits in: the rail on the left, a header strip, and a
 * scrolling body. The pages differ in what goes in the header and the body, not in this.
 */

import { useState } from "react";
import { ArrowDown, Menu } from "./icons";
import { Sidebar } from "./Sidebar";

interface Props {
  /** Job id of the run on screen, so the rail can mark its row. */
  current?: string | null;
  header?: React.ReactNode;
  /** Passed to the scrolling body. Nothing scrolls it on its own — see `useFollow`. */
  scrollRef?: (node: HTMLDivElement | null) => void;
  /** Offered only while the bottom is off screen: with no auto-scroll, work happening
   *  below the fold is otherwise invisible. */
  jump?: () => void;
  children: React.ReactNode;
  /** Below the scroll area, outside it: the composer, where a page has one. */
  footer?: React.ReactNode;
}

export function Shell({ current = null, header, scrollRef, jump, children, footer }: Props) {
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
          {header}
        </header>
        <div className="scroll" ref={scrollRef}>
          {children}
        </div>
        {jump && (
          <button className="jump" onClick={jump} aria-label="Scroll to the newest">
            <ArrowDown />
          </button>
        )}
        {footer}
      </main>
    </div>
  );
}
