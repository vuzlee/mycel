/**
 * Where you are, and everything you have run.
 *
 * The history comes from `GET /conversations` now, not `localStorage`: it is the same
 * list on a second machine, which is the whole reason it moved to Postgres.
 *
 * Below 760px the rail slides in over the page instead of taking a column, so the
 * history stays reachable on a phone rather than disappearing with the layout.
 */


import { Link, NavLink, useNavigate } from "react-router-dom";
import type { Thread } from "../api";
import { useThreads } from "../threads";
import { resolve, useTheme } from "../theme";
import { Account } from "./Account";
import { Bars, Chat, Close, Digest, Moon, Mycelium, Plus, Sun } from "./icons";

interface Props {
  /** Job id of the run on screen, so its row reads as current. */
  current: string | null;
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ current, open, onClose }: Props) {
  const [theme, choose] = useTheme();
  const { threads } = useThreads();
  const navigate = useNavigate();
  const dark = resolve(theme) === "dark";

  const open_ = (thread: Thread): void => {
    const page = thread.kind === "report" ? "/reports" : "/";
    navigate(thread.job_id ? `${page}?job=${thread.job_id}` : page);
    onClose();
  };

  return (
    <>
      <div className="scrim" data-open={open} onClick={onClose} />
      <aside className="rail" data-open={open}>
        <header>
          {/* The wordmark goes home, the way a wordmark does everywhere else. Signed in,
              `/home` is still worth reaching: it is where what this thing does is written
              down, and there is a way straight back from it. */}
          <Link className="brand" to="/home" onClick={onClose} title="What Mycel is">
            <span className="mark">
              <Mycelium size={15} />
            </span>
            Mycel
          </Link>
          <button
            className="icon-button"
            onClick={() => choose(dark ? "light" : "dark")}
            title={dark ? "Switch to light" : "Switch to dark"}
            aria-label="Switch theme"
          >
            {dark ? <Sun /> : <Moon />}
          </button>
          <button className="icon-button shut" onClick={onClose} aria-label="Close menu">
            <Close />
          </button>
        </header>

        <nav className="nav">
          <NavLink to="/" end onClick={onClose}>
            <Chat />
            Ask
          </NavLink>
          <NavLink to="/reports" onClick={onClose}>
            <Digest />
            Progress report
          </NavLink>
          <NavLink to="/dashboard" onClick={onClose}>
            <Bars />
            Dashboard
          </NavLink>
        </nav>

        <button
          className="new-run"
          onClick={() => {
            navigate("/");
            onClose();
          }}
        >
          <Plus />
          New run
        </button>

        <h2 className="label">Recent</h2>
        {threads.length === 0 ? (
          <p className="empty">Runs you start appear here, ready to reopen.</p>
        ) : (
          <ol>
            {threads.map((thread) => (
              <li key={thread.id}>
                <button
                  aria-current={thread.job_id !== null && thread.job_id === current}
                  title={thread.title}
                  onClick={() => open_(thread)}
                >
                  {thread.title}
                  {/* A thread the worker never picked up is shown, not hidden: a queued
                      run nobody is working on is exactly what someone needs to see. */}
                  {thread.status !== null && thread.status !== "done" && (
                    <span className="state">{thread.status}</span>
                  )}
                </button>
              </li>
            ))}
          </ol>
        )}

        {/* The same menu the home page has, in the same shape: profile, settings, help,
            sign out. One component, so the account is never somewhere else. */}
        <Account where="rail" />
      </aside>
    </>
  );
}
