/**
 * What the account menu opens: the account, the one setting, and how to use this.
 *
 * Panels rather than pages — each is a few blocks someone reads and dismisses, and all
 * three live here because they are the same size and the same shape. A file each would
 * be three files of twenty lines.
 */

import type { Thread } from "../api";
import { useAuth } from "../auth";
import type { Theme } from "../theme";
import { useTheme } from "../theme";

const REPO = "https://github.com/vuzlee/mycel";
const CONTACT = "levu040102@gmail.com";

/** The account, as the server knows it. Read-only: `app.user` holds an id, an email and
 *  a password hash, and no route changes any of them — a form that cannot save is worse
 *  than a page that says what is true. */
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
        with you. Changing the address or the password is not built yet.
      </p>
    </>
  );
}

const THEMES: { value: Theme; label: string; how: string }[] = [
  { value: "system", label: "Match my machine", how: "Follows the device's own setting." },
  { value: "light", label: "Light", how: "Always light, whatever the device says." },
  { value: "dark", label: "Dark", how: "Always dark, whatever the device says." },
];

/** One setting, because there is one. "System" is a real third option rather than the
 *  absence of a choice: a boolean cannot say "follow the machine". */
export function SettingsPanel() {
  const [theme, choose] = useTheme();

  return (
    <>
      <section>
        <h3 className="label">Appearance</h3>
        <div className="choice-list">
          {THEMES.map((option) => (
            <button
              key={option.value}
              aria-pressed={theme === option.value}
              onClick={() => choose(option.value)}
            >
              <b>{option.label}</b>
              <span className="muted">{option.how}</span>
            </button>
          ))}
        </div>
        <p className="muted">Kept in this browser — another machine keeps its own.</p>
      </section>
    </>
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
