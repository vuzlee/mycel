import { useEffect } from "react";

/** Cmd/Ctrl + `key` runs `action`. */
export function useHotkey(key: string, action: () => void): void {
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === key) {
        event.preventDefault();
        action();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [key, action]);
}
