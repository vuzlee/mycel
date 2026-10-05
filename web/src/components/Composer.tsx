/**
 * Ask a question. Enter sends, Shift+Enter breaks the line.
 *
 * Sources are chips: the + button opens the list, and so does typing `@`. A file dropped on
 * the composer goes into the user's documents.
 */

import { useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Chip } from "../api";
import { ChipMenu, PickedChips } from "./ChipMenu";
import { ArrowUp, Plus, Spinner } from "./icons";

export interface ComposerHandle {
  focus: () => void;
}

/** Shown under the composer while Knowledge is locked. */
export const PROCESSING_NOTE =
  "Note: documents are being processed — the knowledge base is unavailable until they are ready.";

interface Props {
  busy: boolean;
  seed: string;
  handle: React.Ref<ComposerHandle>;
  chips: Chip[];
  onChips: (chips: Chip[]) => void;
  /** True while a document is processing: Knowledge cannot be asked. */
  knowledgeLocked: boolean;
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
  onAsk,
  onDropFiles,
}: Props) {
  const [value, setValue] = useState(seed);
  const [menu, setMenu] = useState(false);
  const [over, setOver] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);

  useImperativeHandle(handle, () => ({ focus: () => box.current?.focus() }), []);

  useEffect(() => {
    if (!seed) return;
    setValue(seed);
    box.current?.focus();
  }, [seed]);

  // Grow with the text rather than scroll inside a one-line box, up to the CSS max-height.
  useEffect(() => {
    const node = box.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${node.scrollHeight}px`;
  }, [value]);

  const mention = /(?:^|\s)@(\w*)$/.exec(value);
  const locked: Partial<Record<Chip, string>> = knowledgeLocked
    ? { knowledge: "Documents are being processed" }
    : {};
  const blocked = knowledgeLocked && chips.includes("knowledge");

  const pick = (chip: Chip): void => {
    onChips([...chips, chip]);
    // Drop the `@word` being typed; the chip replaces it.
    if (mention) setValue(value.slice(0, value.length - (mention[1] ?? "").length - 1));
    setMenu(false);
    box.current?.focus();
  };

  const submit = (): void => {
    const question = value.trim();
    if (!question || busy || blocked) return;
    onAsk(question);
    setValue("");
  };

  return (
    <div className="composer">
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
          <div className="chip-anchor">
            <button
              type="button"
              className="icon-button add-source"
              aria-label="Add a source"
              title="Add a source"
              onClick={() => setMenu((open) => !open)}
            >
              <Plus />
            </button>
            {(menu || mention) && (
              <ChipMenu
                picked={chips}
                locked={locked}
                filter={mention?.[1] ?? ""}
                onPick={pick}
              />
            )}
          </div>
          <div className="composer-field">
            <PickedChips
              picked={chips}
              dimmed={locked}
              onRemove={(chip) => onChips(chips.filter((c) => c !== chip))}
            />
            <textarea
              ref={box}
              rows={1}
              value={value}
              placeholder={
                chips.length === 0 ? "Ask anything — add a source with + or @" : "Ask…"
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
          <button
            className="send"
            type="submit"
            disabled={busy || blocked || !value.trim()}
            aria-label={busy ? "Running" : "Ask"}
            title={busy ? "Running" : "Ask"}
          >
            {busy ? <Spinner className="spin" size={15} /> : <ArrowUp />}
          </button>
        </div>
      </form>
      {blocked ? (
        <p className="hint note">{PROCESSING_NOTE}</p>
      ) : (
        <p className="hint">
          <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line ·{" "}
          <kbd>@</kbd> for a source
        </p>
      )}
    </div>
  );
}
