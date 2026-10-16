/** Ask a question. Enter sends, Shift+Enter breaks the line. */

import { useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Chip, ModelChoice } from "../api";
import { ChipMenu, iconOf, labelOf } from "./ChipMenu";
import { ModelPicker } from "./ModelPicker";
import { Hub, Spinner, Sprout } from "./icons";

export interface ComposerHandle {
  focus: () => void;
}

/** Shown under the composer while Knowledge is locked. */
export const PROCESSING_NOTE =
  "Note: documents are being processed — the knowledge base is unavailable until they are ready.";

interface Props {
  busy: boolean;
  seed: { text: string } | null;
  handle: React.Ref<ComposerHandle>;
  chips: Chip[];
  onChips: (chips: Chip[]) => void;
  /** True while a document is processing: Knowledge cannot be asked. */
  knowledgeLocked: boolean;
  /** Models that are on; the picker hides itself when there is only one. */
  models: ModelChoice[];
  model: string | null;
  onModel: (ref: string) => void;
  onAsk: (question: string) => void;
  onDropFiles: (files: File[]) => void;
}

export function Composer({
  busy,
  seed,
  handle,
  chips,
  onChips,
  knowledgeLocked,
  models,
  model,
  onModel,
  onAsk,
  onDropFiles,
}: Props) {
  const [value, setValue] = useState(seed?.text ?? "");
  const [menu, setMenu] = useState(false);
  const [over, setOver] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const anchor = useRef<HTMLDivElement>(null);

  useImperativeHandle(handle, () => ({ focus: () => box.current?.focus() }), []);

  useEffect(() => {
    if (!seed) return;
    setValue(seed.text);
    box.current?.focus();
  }, [seed]);

  // Grow with the text rather than scroll inside a one-line box, up to the CSS max-height.
  useEffect(() => {
    const node = box.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${node.scrollHeight}px`;
  }, [value]);

  useEffect(() => {
    if (!menu) return;
    const close = (event: MouseEvent): void => {
      if (!anchor.current?.contains(event.target as Node)) setMenu(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menu]);

  const mention = /(?:^|\s)@(\w*)$/.exec(value);
  const locked: Partial<Record<Chip, string>> = knowledgeLocked
    ? { knowledge: "Documents are being processed" }
    : {};
  const blocked = knowledgeLocked && chips.includes("knowledge");

  const toggle = (chip: Chip): void => {
    onChips(chips.includes(chip) ? chips.filter((c) => c !== chip) : [...chips, chip]);
    // Drop the `@word` being typed; the tick replaces it.
    if (mention) {
      setValue(value.slice(0, value.length - (mention[1] ?? "").length - 1));
      box.current?.focus();
    }
  };

  const submit = (): void => {
    const question = value.trim();
    if (!question || busy || blocked) return;
    onAsk(question);
    setValue("");
  };

  return (
    <div className="composer">
      {chips.length > 0 && (
        <div className="source-chips" role="group" aria-label="Sources">
          {chips.map((chip) => (
            <button
              key={chip}
              type="button"
              className="source-chip"
              aria-pressed
              title={`Remove ${labelOf(chip)}`}
              onClick={() => toggle(chip)}
            >
              {iconOf(chip)}
              {labelOf(chip)}
            </button>
          ))}
        </div>
      )}
      <form
        data-over={over}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
        onDragOver={(event) => {
          if (!event.dataTransfer.types.includes("Files")) return;
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          if (event.dataTransfer.files.length === 0) return;
          event.preventDefault();
          setOver(false);
          onDropFiles(Array.from(event.dataTransfer.files));
        }}
      >
        <div className="composer-row">
          <div className="chip-anchor" ref={anchor}>
            <button
              type="button"
              className="icon-button add-source"
              aria-label="Sources"
              title={chips.length ? chips.map(labelOf).join(", ") : "Add a source"}
              data-on={chips.length > 0}
              onClick={() => setMenu((open) => !open)}
            >
              <Hub />
              {chips.length > 0 && <span className="source-count">{chips.length}</span>}
            </button>
            {(menu || mention) && (
              <ChipMenu
                picked={chips}
                locked={locked}
                filter={mention?.[1] ?? ""}
                onToggle={toggle}
              />
            )}
          </div>
          <div className="composer-field">
            <textarea
              ref={box}
              rows={1}
              value={value}
              placeholder={
                chips.length === 0
                  ? "Ask anything, or type @ to pick a source"
                  : `Ask with ${chips.map(labelOf).join(", ")}…`
              }
              aria-label="Your question"
              onChange={(event) => setValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setMenu(false);
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submit();
                }
              }}
            />
          </div>
          {models.length > 1 && model !== null && (
            <ModelPicker models={models} value={model} onChange={onModel} />
          )}
          <button
            className="send"
            type="submit"
            disabled={busy || blocked || !value.trim()}
            aria-label={busy ? "Running" : "Ask"}
            title={busy ? "Running" : "Ask"}
          >
            {busy ? <Spinner className="spin" size={15} /> : <Sprout size={16} />}
          </button>
        </div>
      </form>
      {blocked ? (
        <p className="hint note">{PROCESSING_NOTE}</p>
      ) : (
        <p className="hint">
          <kbd>Enter</kbd> to send <kbd>Shift</kbd>+<kbd>Enter</kbd> new line <kbd>@</kbd> pick a
          source
        </p>
      )}
    </div>
  );
}
