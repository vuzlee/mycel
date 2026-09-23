/**
 * Ask for a reset link.
 *
 * The answer is the same whether or not the address has an account, and the page says so
 * out loud: a screen that reads "no such account" is a screen anyone can use to find out
 * who has one. Saying it plainly is better than letting someone wonder whether it worked.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { forgotPassword } from "../api";
import { Mycelium, Spinner } from "../components/icons";

export function Forgot() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const submit = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    try {
      await forgotPassword(email);
      setSent(true);
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

        <h1>Reset your password</h1>

        {sent ? (
          <>
            <p className="lede">
              If that address has an account, a link is on its way. It works once and stops
              working in an hour.
            </p>
            <p className="switch">
              <Link to="/login">Back to sign in</Link>
            </p>
          </>
        ) : (
          <>
            <p className="lede">
              Give the address you sign in with and we will send a link to set a new
              password.
            </p>

            <form
              onSubmit={(event) => {
                event.preventDefault();
                void submit();
              }}
            >
              <label>
                <span className="label">Email</span>
                <input
                  type="email"
                  autoComplete="username"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </label>

              {failure && <p className="failure">{failure}</p>}

              <button className="primary" type="submit" disabled={busy}>
                {busy && <Spinner className="spin" size={14} />}
                Send the link
              </button>
            </form>

            <p className="switch">
              Remembered it? <Link to="/login">Sign in</Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
