/**
 * Light, dark, or whatever the machine says.
 *
 * The choice lives in `localStorage` and on `<html data-theme>`, not in React state: it
 * has to be applied before the first paint or the page flashes the wrong theme on every
 * reload, and `index.html` sets the attribute from the same key for exactly that reason.
 *
 * "System" is a real third option rather than the absence of a choice — someone whose
 * laptop turns dark at sunset wants the app to follow, and a boolean cannot say that.
 */

import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";

const KEY = "mycel.theme";

export function stored(): Theme {
  const found = localStorage.getItem(KEY);
  return found === "light" || found === "dark" ? found : "system";
}

/** What is actually on screen, once "system" has been asked what it means. */
export function resolve(theme: Theme): "light" | "dark" {
  if (theme !== "system") return theme;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function apply(theme: Theme): void {
  if (theme === "system") {
    delete document.documentElement.dataset.theme;
    localStorage.removeItem(KEY);
    return;
  }
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(KEY, theme);
}

export function useTheme(): [Theme, (next: Theme) => void] {
  const [theme, set] = useState<Theme>(stored);

  useEffect(() => apply(theme), [theme]);

  const choose = useCallback((next: Theme) => set(next), []);
  return [theme, choose];
}
