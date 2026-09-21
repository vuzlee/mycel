/** Ask a question. Enter sends, Shift+Enter breaks the line. */

import { useEffect, useImperativeHandle, useRef, useState } from "react";
import { ArrowUp, Spinner } from "./icons";

export interface ComposerHandle {
  focus: () => void;
}

interface Props {
  busy: boolean;
  seed: string;
  handle: React.Ref<ComposerHandle>;
  onAsk: (question: string) => void;
}

export function Composer({ busy, seed, handle, onAsk }: Props) {
  const [value, setValue] = useState(seed);
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

  const submit = (): void => {
    const question = value.trim();
    if (!question || busy) return;
    onAsk(question);
    setValue("");
  };

  return (
    <div className="composer">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <textarea
          ref={box}
          rows={1}
          value={value}
          placeholder="Ask about the work, or anything else…"
          aria-label="Your question"
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <button
          className="send"
          type="submit"
          disabled={busy || !value.trim()}
          aria-label={busy ? "Running" : "Ask"}
          title={busy ? "Running" : "Ask"}
        >
          {busy ? <Spinner className="spin" size={15} /> : <ArrowUp />}
        </button>
      </form>
      <p className="hint">
        <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line
      </p>
    </div>
  );
}
