/**
 * Sign in.
 *
 * Its own page rather than a toggle beside registration: the two now end differently —
 * signing in lands you in the app, registering leaves you here — and a single form that
 * branches on a flag hides that difference at exactly the moment it matters.
 *
 * Arriving from `/register` carries a notice in the router state, so a new account says
 * so on the screen that asks it to prove itself.
 */

import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { Credentials } from "../components/Credentials";
import { Mycelium } from "../components/icons";

interface Sent {
  /** Where the guard bounced us from, to return to after signing in. */
  from?: string;
  /** What `/register` wants said here. */
  notice?: string;
}

export function Login() {
  const { user, signIn } = useAuth();
  const location = useLocation();
  const sent = (location.state as Sent | null) ?? {};
  const [failure, setFailure] = useState<string | null>(null);

  if (user) return <Navigate to={sent.from ?? "/"} replace />;

  return (
    <div className="gate">
      <div className="card">
        <Link className="brand" to="/home">
          <span className="mark">
            <Mycelium size={15} />
          </span>
          Mycel
        </Link>

        <h1>Sign in</h1>
        <p className="lede">
          Ask about your team's week, the numbers behind it, or anything else. An account
          keeps your runs, so they are still there on another machine tomorrow.
        </p>

        {sent.notice && <p className="notice">{sent.notice}</p>}

        <Credentials
          verb="Sign in"
          onSubmit={signIn}
          failure={failure}
          onFailure={setFailure}
        />

        <p className="switch">
          No account yet? <Link to="/register">Create one</Link>
        </p>
      </div>
    </div>
  );
}
