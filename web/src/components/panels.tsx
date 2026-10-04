/**
 * What the account menu opens: the account, the settings, and how to use this.
 *
 * Panels rather than pages — each is a few blocks someone reads and dismisses, and all
 * three live here because they are the same size and the same shape. A file each would
 * be three files of twenty lines.
 */

import { useEffect, useState } from "react";
import type { GoogleStatus, JiraStatus, Thread } from "../api";
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
        Your runs are kept under this account, so signing in on another machine brings them
        with you. The address is the identity here and cannot be changed.
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
        {done && <p className="notice">Changed. Every other browser has been signed out.</p>}

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

/** Three settings: how it looks here, which calendar it may read, and which Jira it
 *  writes to as you.
 *
 *  They sit together because all three answer "how does this behave for me", and none is
 *  big enough for a screen of its own. Appearance is per-browser; the two connections are
 *  per-account, which the copy under each one says. */
export function SettingsPanel() {
  const [theme, choose] = useTheme();

  return (
    <>
      <section>
        <h3 className="label">Appearance</h3>
        <div className="theme-picker">
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
        <p className="muted">Kept in this browser — another machine keeps its own.</p>
      </section>

      <GoogleSection />
      <JiraSection />
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

/** Connecting a Google account, so a question about the calendar has one to read.
 *
 *  Three states, and the first is about the deployment rather than the person: a machine
 *  with no OAuth client cannot connect anything, and saying so is better than a button that
 *  leads to an error. Then connected, and not. */
function GoogleSection() {
  const [status, setStatus] = useState<GoogleStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [came] = useState(() => outcome("google"));

  useEffect(() => {
    void fetchGoogle().then(setStatus).catch(() => setStatus(null));
    // Cleared here rather than in both sections: whichever round just finished owns the
    // query string, and clearing it twice is harmless only until one of them clears the
    // other's outcome before it has been read.
    if (came) window.history.replaceState({}, "", window.location.pathname);
  }, [came]);

  const drop = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    try {
      await disconnectGoogle();
      setStatus(await fetchGoogle());
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h3 className="label">Google Calendar</h3>

      {status === null && <p className="muted">Checking…</p>}

      {status && !status.configured && (
        <p className="muted">
          This deployment has no Google client configured, so no calendar can be connected.
          Whoever runs it sets <code>GOOGLE_CLIENT_ID</code>,{" "}
          <code>GOOGLE_CLIENT_SECRET</code> and <code>TOKEN_ENCRYPTION_KEY</code>.
        </p>
      )}

      {status?.configured && status.email && (
        <>
          <div className="identity">
            <span className="avatar big" aria-hidden>
              <Calendar size={17} />
            </span>
            <div>
              <b>{status.email}</b>
              <span className="muted">
                Connected{" "}
                {status.connected_at
                  ? new Date(status.connected_at).toLocaleDateString()
                  : ""}
              </span>
            </div>
          </div>
          <p className="muted">
            Questions about your time read this calendar, and a booking you agree to is
            written to it. Nothing else is read, and nothing is ever deleted.
          </p>
          {failure && <p className="failure">{failure}</p>}
          <button onClick={() => void drop()} disabled={busy}>
            {busy && <Spinner className="spin" size={14} />}
            Disconnect
          </button>
        </>
      )}

      {status?.configured && !status.email && (
        <>
          <p className="muted">
            Connect one and you can ask what is on this afternoon, or say "3pm tomorrow,
            team, half an hour" and agree to what it reads back. Nothing is written until you
            do — and nothing here can delete an event.
          </p>
          {came === "failed" && (
            <p className="failure">That did not finish. Nothing was connected.</p>
          )}
          <button className="primary" onClick={connectGoogle}>
            <Calendar size={14} />
            Connect Google Calendar
          </button>
        </>
      )}
    </section>
  );
}

/** Connecting a Jira account, so what the app writes carries your name and not the host's.
 *
 *  Four states rather than the Google section's three, and the fourth is the one that
 *  matters: whether this grant is the one every background sync runs on. Disconnecting
 *  that one stops the syncing, and somebody about to click Disconnect has to be told
 *  before they do rather than after. */
function JiraSection() {
  const [status, setStatus] = useState<JiraStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [came] = useState(() => outcome("jira"));

  useEffect(() => {
    void fetchJira().then(setStatus).catch(() => setStatus(null));
  }, [came]);

  const drop = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    try {
      await disconnectJira();
      setStatus(await fetchJira());
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h3 className="label">Jira</h3>

      {status === null && <p className="muted">Checking…</p>}

      {status && !status.configured && (
        <p className="muted">
          This deployment has no Jira OAuth client configured, so no account can be
          connected. Whoever runs it sets <code>JIRA_CLIENT_ID</code>,{" "}
          <code>JIRA_CLIENT_SECRET</code> and <code>TOKEN_ENCRYPTION_KEY</code>.
        </p>
      )}

      {status?.configured && status.display_name && (
        <>
          <div className="identity">
            <span className="avatar big" aria-hidden>
              <Board size={17} />
            </span>
            <div>
              <b>{status.display_name}</b>
              <span className="muted">
                Connected{" "}
                {status.connected_at
                  ? new Date(status.connected_at).toLocaleDateString()
                  : ""}
              </span>
            </div>
          </div>
          <p className="muted">
            A comment, a status change or a new ticket is written under this name. Nothing
            is written until you have read it back and agreed to it, and nothing here can
            delete anything.
          </p>
          {status.is_syncer && (
            <p className="muted">
              <b>Every background sync runs on this account.</b> Last sync{" "}
              {status.last_sync_at
                ? new Date(status.last_sync_at).toLocaleString()
                : "never"}
              . Disconnecting stops the syncing until somebody else connects.
            </p>
          )}
          {failure && <p className="failure">{failure}</p>}
          <button onClick={() => void drop()} disabled={busy}>
            {busy && <Spinner className="spin" size={14} />}
            Disconnect
          </button>
          <p className="muted">
            Disconnecting here forgets the token. To withdraw the permission at
            Atlassian's end as well, remove the app at{" "}
            <code>id.atlassian.com</code> → Account settings → Connected apps.
          </p>
        </>
      )}

      {status?.configured && !status.display_name && (
        <>
          <p className="muted">
            Connect one and you can say "comment on MYC-12 that it's done" or "create a task
            for the login timeout, assign it to Nam" — written under your own name, after
            you have read it back and agreed. Jira cannot correct the author of something
            already written, which is why there is no shared account to fall back on.
          </p>
          {!status.syncer_exists && (
            <p className="muted">
              <b>Nobody has connected Jira yet</b>, so nothing is syncing and the dashboard
              is empty. The first person to connect becomes the one every background sync
              runs on.
            </p>
          )}
          {came === "failed" && (
            <p className="failure">That did not finish. Nothing was connected.</p>
          )}
          <button className="primary" onClick={connectJira}>
            <Board size={14} />
            Connect Jira
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
          , or write to <a href={`mailto:${CONTACT}`}>{CONTACT}</a>. Replies are from one
          person, so give it a day.
        </p>
      </section>
    </>
  );
}
