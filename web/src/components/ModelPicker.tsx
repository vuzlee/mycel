import { useEffect, useRef, useState } from "react";
import type { ModelChoice } from "../api";
import { Check, Chevron } from "./icons";

/** The model for the next question: a small button that opens a list above the composer. */
export function ModelPicker({
  models,
  value,
  onChange,
}: {
  models: ModelChoice[];
  value: string;
  onChange: (ref: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const current = models.find((m) => m.ref === value);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent): void => {
      if (
        event instanceof KeyboardEvent
          ? event.key === "Escape"
          : !root.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <div className="model-pick" ref={root}>
      <button
        type="button"
        className="model-pick-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Model"
        onClick={() => setOpen(!open)}
      >
        <span className="model-pick-label">{current?.label ?? "Model"}</span>
        <Chevron size={11} className="model-pick-chevron" />
      </button>
      {open && (
        <ul className="model-pick-menu" role="listbox" aria-label="Model">
          {models.map((m) => (
            <li key={m.ref}>
              <button
                type="button"
                role="option"
                aria-selected={m.ref === value}
                onClick={() => {
                  onChange(m.ref);
                  setOpen(false);
                }}
              >
                <span className="model-pick-label">{m.label}</span>
                <span className="model-pick-tag">
                  {m.source === "own" ? "your key" : "included"}
                </span>
                <span className="model-pick-check">{m.ref === value && <Check size={12} />}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
