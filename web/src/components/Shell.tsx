/** The frame every signed-in page sits in: rail, header strip, scrolling body. */

import { useEffect, useRef, useState } from "react";
import { ArrowDown, Menu, PanelLeft } from "./icons";
import { Sidebar } from "./Sidebar";

interface Props {
  /** Job id of the run on screen, so the rail can mark its row. */
  current?: string | null;
  /** Passed to the scrolling body, so the jump button knows how far the bottom is. */
  scrollRef?: (node: HTMLDivElement | null) => void;
  /** Offered only while the bottom is off screen. Nothing scrolls on its own, so this is
   *  the only thing that offers to. */
  jump?: () => void;
  children: React.ReactNode;
  /** Below the scroll area, outside it: the composer, where a page has one. */
  footer?: React.ReactNode;
  /** The map of a long conversation, floating in the gutter beside the prose. Inside `.main`
   *  rather than beside it: it is positioned against the body it maps, and it takes no
   *  column — a column would shove the conversation off centre at the second question. */
  aside?: React.ReactNode;
}

const FOLD_KEY = "mycel.rail-folded";

export function Shell({ current = null, scrollRef, jump, children, footer, aside }: Props) {
  const [menu, setMenu] = useState(false);
  const [folded, setFolded] = useState(() => {
    try {
      return localStorage.getItem(FOLD_KEY) === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(FOLD_KEY, folded ? "1" : "0");
    } catch {
      /* a remembered fold is a convenience */
    }
  }, [folded]);

  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const root = document.documentElement;
    root.setAttribute("data-rail-moving", "");
    const done = window.setTimeout(() => root.removeAttribute("data-rail-moving"), 320);
    return () => {
      window.clearTimeout(done);
      root.removeAttribute("data-rail-moving");
    };
  }, [folded]);

  return (
    <div className="shell" data-folded={folded}>
      <Sidebar
        current={current}
        open={menu}
        onClose={() => setMenu(false)}
        onCollapse={() => setFolded(true)}
      />
      <main className="main">
        <header>
          <button
            className="icon-button reveal"
            onClick={() => setMenu(true)}
            aria-label="Show menu"
          >
            <Menu />
          </button>
          {folded && (
            <button
              className="icon-button unfold"
              onClick={() => setFolded(false)}
              aria-label="Expand sidebar"
              title="Expand sidebar"
            >
              <PanelLeft />
            </button>
          )}
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
