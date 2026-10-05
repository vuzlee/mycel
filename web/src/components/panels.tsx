/**
 * What the account menu opens: the account, the settings, and how to use this.
 *
 * Panels rather than pages — each is a few blocks someone reads and dismisses, and all
 * three live here because they are the same size and the same shape. A file each would
 * be three files of twenty lines.
 */

import { useEffect, useState } from "react";
import type { Thread } from "../api";
import {
  changePassword,
  connectGoogle,
  connectJira,
  disconnectGoogle,
  disconnectJira,
  fetchGoogle,
  fetchJira,
} from "../api";
import { useAuth } from "../auth";
import { Board, Calendar, Moon, Screen, Spinner, Sun } from "./icons";
import type { Theme } from "../theme";
import { useTheme } from "../theme";

const REPO = "https://github.com/vuzlee/mycel";
const CONTACT = "levu040102@gmail.com";

/** The account, as the server knows it. The address cannot be changed — it is the
 *  identity — and the password can, which is why one of the two has a form. */
export function ProfilePanel({ threads }: { threads: Thread[] }) {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <>
      <div className="identity">
        <span className="avatar big" aria-hidden>
          {user.email.charAt(0).toUpperCase()}
        </span>
        <div>
          <b>{user.email}</b>
          <span className="muted">Account #{user.id}</span>
        </div>
      </div>

      <dl className="facts">
        <div>
          <dt>Runs kept</dt>
          <dd>{threads.length}</dd>
        </div>
        <div>
          <dt>Sign-in</dt>
          <dd>Password</dd>
        </div>
      </dl>

      <p className="muted">
        Your runs are kept under this account, so signing in on another machine
        brings them with you. The address is the identity here and cannot be
        changed.
      </p>

      <PasswordForm />
    </>
  );
}

/** Changing the password needs the current one even though a valid cookie is already in
 *  hand: a borrowed laptop is exactly the case that protects against. Every other session
 *  ends, and this one does not — you stay in the tab you are typing in. */
function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const submit = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    setDone(false);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setDone(true);
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h3 className="label">Change password</h3>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label>
          <span className="label">Current password</span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        </label>

        <label>
          <span className="label">New password</span>
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
          <span className="hint">At least 8 characters.</span>
        </label>

        {failure && <p className="failure">{failure}</p>}
        {done && (
          <p className="notice">
            Changed. Every other browser has been signed out.
          </p>
        )}

        <button className="primary" type="submit" disabled={busy}>
          {busy && <Spinner className="spin" size={14} />}
          Change it
        </button>
      </form>
    </section>
  );
}

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
export function SettingsPanel() {
  const [theme, choose] = useTheme();

  return (
    <>
      <section className="settings-zone">
        <h3 className="zone-title">Accounts</h3>
        <div className="settings-grid">
          {CONNECTIONS.map((p) => (
            <Connection key={p.id} provider={p} />
          ))}
        </div>
      </section>

      <section className="settings-zone appearance">
        <h3 className="zone-title">Appearance</h3>
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
        <span className="muted small">This browser only.</span>
      </section>
    </>
  );
}

/** The outcome of a consent round, which arrives in the query string rather than in a
 *  response: the browser left for the provider's own screen and came back by redirect, so
 *  there was no fetch to answer. Read once and cleared from the address bar, so reloading
 *  the page does not re-announce a connection made ten minutes ago. */
function outcome(provider: "google" | "jira"): "connected" | "failed" | null {
  const query = new URLSearchParams(window.location.search);
  if (query.has(provider)) return "connected";
  if (query.has(`${provider}_error`)) return "failed";
  return null;
}

/** One account a person connects. Adding a provider is one entry in `CONNECTIONS` — the
 *  status call, the consent redirect and the disconnect are all it needs from `api.ts`. */
interface Provider {
  id: "google" | "jira";
  title: string;
  icon: React.ReactNode;
  /** One line, shown before connecting: what connecting opens. */
  offers: string;
  status: () => Promise<{
    configured: boolean;
    who: string | null;
    since: string | null;
    note?: string;
  }>;
  connect: () => void;
  disconnect: () => Promise<void>;
}

const CONNECTIONS: Provider[] = [
  {
    id: "google",
    title: "Google",
    icon: <Calendar size={16} />,
    offers:
      "Your own calendar and mail. Mail is read-only; nothing is deleted.",
    status: async () => {
      const s = await fetchGoogle();
      return { configured: s.configured, who: s.email, since: s.connected_at };
    },
    connect: connectGoogle,
    disconnect: disconnectGoogle,
  },
  {
    id: "jira",
    title: "Jira",
    icon: <Board size={16} />,
    offers: "The projects Jira lets you browse. Writes only after you agree.",
    status: async () => {
      const s = await fetchJira();
      const note = s.display_name
        ? s.projects.length
          ? `Reads ${s.projects.join(", ")}`
          : "Jira lets this account browse no project"
        : undefined;
      return {
        configured: s.configured,
        who: s.display_name,
        since: s.connected_at,
        note,
      };
    },
    connect: connectJira,
    disconnect: disconnectJira,
  },
];

type Status = Awaited<ReturnType<Provider["status"]>>;

/** One provider's card: not set up here, connected, or not yet. */
function Connection({ provider }: { provider: Provider }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [came] = useState(() => outcome(provider.id));

  useEffect(() => {
    void provider
      .status()
      .then(setStatus)
      .catch(() => setStatus(null));
    if (came) window.history.replaceState({}, "", window.location.pathname);
  }, [came, provider]);

  const drop = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    try {
      await provider.disconnect();
      setStatus(await provider.status());
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="connection">
      <header className="connection-head">
        <span className="connection-icon" aria-hidden>
          {provider.icon}
        </span>
        <h4>{provider.title}</h4>
        {status?.who && <span className="pill on">Connected</span>}
      </header>
      {status === null && <p className="muted">Checking…</p>}
      {status && !status.configured && (
        <p className="muted">
          Not set up on this deployment — see docs/setup.md.
        </p>
      )}
      {status?.configured && status.who && (
        <>
          <div className="connection-who">
            <b>{status.who}</b>
            <span className="muted">
              since{" "}
              {status.since ? new Date(status.since).toLocaleDateString() : "—"}
            </span>
          </div>
          {status.note && <p className="muted">{status.note}</p>}
          {failure && <p className="failure">{failure}</p>}
          <button
            className="outline"
            onClick={() => void drop()}
            disabled={busy}
          >
            {busy && <Spinner className="spin" size={14} />}
            Disconnect
          </button>
        </>
      )}
      {status?.configured && !status.who && (
        <>
          <p className="muted">{provider.offers}</p>
          {came === "failed" && (
            <p className="failure">
              That did not finish. Nothing was connected.
            </p>
          )}
          <button className="primary" onClick={provider.connect}>
            Connect {provider.title}
          </button>
        </>
      )}
    </section>
  );
}

const STEPS = [
  {
    title: "Keep your tracker as you already do",
    body: "Mycel reads your Jira project — issues, epics, estimates, worklogs and due dates. Nobody fills in a second form, and nothing here writes back to it.",
  },
  {
    title: "Read the week",
    body: "Ask for a project's progress over any window and it writes it up: what shipped, what is still moving, and which ticket is late.",
  },
  {
    title: "Read the numbers",
    body: "Ask for a count instead and it writes its own SQL against the work data: totals by status, estimated against spent per person, effort logged per day. Every figure comes back with the query that produced it.",
  },
  {
    title: "Ask anything else",
    body: "The same box reads your mailbox and searches the web, so a question does not have to be about your tracker to have an answer.",
  },
];

export function HelpPanel() {
  return (
    <>
      <ol className="steps">
        {STEPS.map((step) => (
          <li key={step.title}>
            <b>{step.title}</b>
            <span className="muted">{step.body}</span>
          </li>
        ))}
      </ol>

      <section>
        <h3 className="label">If something is wrong</h3>
        <p className="muted">
          Open an issue at{" "}
          <a href={`${REPO}/issues`} target="_blank" rel="noreferrer">
            the repository
          </a>
          , or write to <a href={`mailto:${CONTACT}`}>{CONTACT}</a>. Replies are
          from one person, so give it a day.
        </p>
      </section>
    </>
  );
}
