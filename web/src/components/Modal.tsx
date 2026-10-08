/** A dialog over whatever page you were on. */

import { useEffect } from "react";
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

export function Modal({ title, lede, onClose, children, wide }: Props) {
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
        className={wide ? "modal wide" : "modal"}
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
