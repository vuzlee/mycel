/** Light, dark, or whatever the machine says. */

import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";

const KEY = "mycel.theme";

export function stored(): Theme {
  const found = localStorage.getItem(KEY);
  return found === "light" || found === "dark" ? found : "system";
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
