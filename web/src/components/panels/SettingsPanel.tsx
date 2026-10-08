import { useState } from "react";
import { Moon, Person, Screen, Sun } from "../icons";
import type { Theme } from "../../lib/theme";
import { useTheme } from "../../lib/theme";
import { CONNECTIONS, Connection } from "./Connections";

const THEMES: { value: Theme; label: string; icon: JSX.Element }[] = [
  { value: "system", label: "System", icon: <Screen size={17} /> },
  { value: "light", label: "Light", icon: <Sun size={17} /> },
  { value: "dark", label: "Dark", icon: <Moon size={17} /> },
];

/** Three settings: how it looks here, your Google (calendar and mail), and your Jira.
 *
 *  They sit together because all three answer "how does this behave for me", and none is
 *  big enough for a screen of its own. Appearance is per-browser; the two connections are
 *  per-account, which the copy under each one says. */
/** One entry in the Settings sidebar. A new section — Personalization, say — is one more
 *  entry here and a component that renders its own page; nothing else changes. */
interface SettingsSection {
  id: string;
  label: string;
  icon: JSX.Element;
  hint: string;
  render: () => JSX.Element;
}

const SECTIONS: SettingsSection[] = [
  {
    id: "appearance",
    label: "Appearance",
    icon: <Screen size={15} />,
    hint: "How it looks in this browser.",
    render: () => <AppearancePage />,
  },
  {
    id: "accounts",
    label: "Accounts",
    icon: <Person size={15} />,
    hint: "The accounts Mycel reads and writes as you.",
    render: () => <AccountsPage />,
  },
];

export function SettingsPanel() {
  const [active, setActive] = useState(SECTIONS[0]!.id);
  const section = SECTIONS.find((s) => s.id === active) ?? SECTIONS[0]!;

  return (
    <div className="settings">
      <nav className="settings-nav" aria-label="Settings sections">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            aria-current={s.id === active ? "page" : undefined}
            onClick={() => setActive(s.id)}
          >
            {s.icon}
            {s.label}
          </button>
        ))}
      </nav>
      <div className="settings-page">
        <header>
          <h3>{section.label}</h3>
          <p className="muted">{section.hint}</p>
        </header>
        {section.render()}
      </div>
    </div>
  );
}

function AccountsPage() {
  return (
    <div className="settings-grid">
      {CONNECTIONS.map((p) => (
        <Connection key={p.id} provider={p} />
      ))}
    </div>
  );
}

function AppearancePage() {
  const [theme, choose] = useTheme();
  return (
    <div className="theme-picker compact" role="group" aria-label="Theme">
      {THEMES.map((option) => (
        <button
          key={option.value}
          aria-pressed={theme === option.value}
          onClick={() => choose(option.value)}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** The outcome of a consent round, which arrives in the query string rather than in a
 *  response: the browser left for the provider's own screen and came back by redirect, so
 *  there was no fetch to answer. Read once and cleared from the address bar, so reloading
 *  the page does not re-announce a connection made ten minutes ago. */
