/**
 * A dialog over whatever page you were on.
 *
 * Profile, settings and help are things you check and dismiss, not places you go — a
 * route for each would drop the run you were watching and give the browser a back button
 * to undo it. They open here, over the page, and close where you left off.
 *
 * Escape closes it, and so does the scrim; a dialog that can only be dismissed by its own
 * button is one people click around.
 */

import { useEffect } from "react";
import { Close } from "./icons";

interface Props {
  title: string;
  /** Said under the title, when the dialog needs a sentence before its content. */
  lede?: string;
  onClose: () => void;
  children: React.ReactNode;
}

export function Modal({ title, lede, onClose, children }: Props) {
  useEffect(() => {
    const key = (event: KeyboardEvent): void => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);

  return (
    <div className="scrim asking" data-open onClick={onClose}>
      <div
        className="modal"
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
