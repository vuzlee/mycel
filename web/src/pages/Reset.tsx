/**
 * Set a new password from a link.
 *
 * The token is in the query string, which is where a link can carry it. It is not put in
 * any field: it is not something to type, and showing it invites pasting it somewhere.
 *
 * Every session of the account ends here, this browser included, so the page sends you to
 * the sign-in form rather than pretending you are already in.
 */

import { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { resetPassword } from "../api";
import { Mycelium, Spinner } from "../components/icons";

export function Reset() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  // A link with no token is not a form to fill in; it is a link that was cut in half.
  if (!token) return <Navigate to="/forgot" replace />;

  const submit = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    try {
      await resetPassword(token, password);
      navigate("/login", {
        replace: true,
        state: { notice: "Your password is set. Sign in with it." },
      });
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="gate">
      <div className="card">
        <Link className="brand" to="/home">
          <span className="mark">
            <Mycelium size={15} />
          </span>
          Mycel
        </Link>

        <h1>Choose a new password</h1>
        <p className="lede">
          This signs out every browser that is still signed in to the account, including
          this one.
        </p>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label>
            <span className="label">New password</span>
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <span className="hint">At least 8 characters.</span>
          </label>

          {failure && <p className="failure">{failure}</p>}

          <button className="primary" type="submit" disabled={busy}>
            {busy && <Spinner className="spin" size={14} />}
            Set the password
          </button>
        </form>

        <p className="switch">
          Link expired? <Link to="/forgot">Ask for another</Link>
        </p>
      </div>
    </div>
  );
}
