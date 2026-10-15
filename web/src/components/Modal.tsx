/** A dialog over whatever page you were on. */

import { useEffect, useRef } from "react";
import { Close } from "./icons";

interface Props {
  title: string;
  /** Said under the title, when the dialog needs a sentence before its content. */
  lede?: string;
  onClose: () => void;
  children: React.ReactNode;
  /** Room for a page to be read, not a form to be filled. */
  wide?: boolean;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

export function Modal({ title, lede, onClose, children, wide }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;

  // Focus moves in on open, Tab stays inside, and focus goes back on close.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    box.current?.focus();
    const key = (event: KeyboardEvent): void => {
      if (event.key === "Escape") close.current();
      if (event.key !== "Tab" || !box.current) return;
      const items = box.current.querySelectorAll<HTMLElement>(FOCUSABLE);
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return event.preventDefault();
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === box.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      before?.focus();
    };
  }, []);

  return (
    <div className="scrim asking" data-open onClick={onClose}>
      <div
        className={wide ? "modal wide" : "modal"}
        ref={box}
        tabIndex={-1}
        role="dialog"
        aria-modal
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <h2>{title}</h2>
            {lede && <p>{lede}</p>}
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            <Close />
          </button>
        </header>
        <div className="body">{children}</div>
      </div>
    </div>
  );
}
