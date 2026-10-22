/** One way in: Google, or an email. An email goes to Google first, straight to that
 *  account's password; a mailbox without Google gets a six-digit code instead. */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Navigate, useLocation, useSearchParams } from "react-router-dom";
import { fetchSignInMethods, googleSignInUrl, requestCode } from "../api";
import { Mycelium, Spinner } from "../components/icons";
import { useAuth } from "../context/AuthContext";

interface Sent {
  /** Where the guard bounced us from, to return to after signing in. */
  from?: string;
}

const REFUSED: Record<string, string> = {
  access_denied: "Google sign-in was cancelled.",
  cancelled: "Google sign-in was cancelled.",
  refused: "Google could not confirm this account. Try again, or use a code.",
  failed: "Google sign-in did not finish. Try again in a moment.",
};

export function Login() {
  const { user, signInWithCode } = useAuth();
  const location = useLocation();
  const [params] = useSearchParams();
  const from = (location.state as Sent | null)?.from;
  const next = `/app${from && from !== "/" ? from : "/"}`;
  const { data: methods } = useQuery({ queryKey: ["signin-methods"], queryFn: fetchSignInMethods });

  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"email" | "code">("email");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(REFUSED[params.get("error") ?? ""] ?? null);

  if (user) return <Navigate to={from ?? "/"} replace />;

  const google = methods?.google ?? false;
  const byCode = methods?.code ?? false;

  const run = async (work: () => Promise<void>): Promise<void> => {
    setBusy(true);
    setFailure(null);
    try {
      await work();
    } catch (error) {
      setFailure(sentence(error instanceof Error ? error.message : String(error)));
    } finally {
      setBusy(false);
    }
  };

  const sendCode = (): Promise<void> =>
    run(async () => {
      await requestCode(email);
      setStep("code");
    });

  return (
    <div className="gate">
      <div className="card signin">
        <Link className="brand" to="/home">
          <span className="mark">
            <Mycelium size={15} />
          </span>
          Mycel
        </Link>

        <h1>{step === "code" ? "Check your mail" : "Sign in"}</h1>
        <p className="lede">
          {step === "code" ? (
            <>
              We sent a six-digit code to <b>{email}</b>. It works for ten minutes.
            </>
          ) : (
            "Your team's week, the numbers behind it, your mail. New here? Signing in makes your account."
          )}
        </p>

        {step === "email" ? (
          <>
            {google && (
              <a className="google" href={googleSignInUrl(null, next)}>
                <GoogleMark />
                Continue with Google
              </a>
            )}
            {google && <div className="or">or</div>}
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (google) window.location.assign(googleSignInUrl(email, next));
                else void sendCode();
              }}
            >
              <label>
                <span className="label">Email</span>
                <input
                  type="email"
                  autoComplete="email"
                  placeholder="you@company.com"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </label>
              {failure && <p className="failure">{failure}</p>}
              <button className="primary" type="submit" disabled={busy || (!google && !byCode)}>
                {busy && <Spinner className="spin" size={14} />}
                Continue
              </button>
            </form>
            {google && byCode && (
              <p className="switch">
                No Google account?{" "}
                <button
                  type="button"
                  className="link"
                  disabled={busy || !email}
                  onClick={() => void sendCode()}
                >
                  Email me a code
                </button>
              </p>
            )}
            {methods && !google && !byCode && (
              <p className="failure">
                This deployment has no way to sign in yet: set a Google client or SMTP.
              </p>
            )}
          </>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void run(() => signInWithCode(email, code));
            }}
          >
            <label>
              <span className="label">Code</span>
              <input
                className="code"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                autoFocus
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
              />
            </label>
            {failure && <p className="failure">{failure}</p>}
            <button className="primary" type="submit" disabled={busy || code.length !== 6}>
              {busy && <Spinner className="spin" size={14} />}
              Sign in
            </button>
            <p className="switch">
              <button
                type="button"
                className="link"
                disabled={busy}
                onClick={() => void sendCode()}
              >
                Send a new code
              </button>
              {" · "}
              <button
                type="button"
                className="link"
                onClick={() => {
                  setStep("email");
                  setCode("");
                  setFailure(null);
                }}
              >
                Use another address
              </button>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}

const sentence = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1) + ".";

function GoogleMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden>
      <path
        fill="#FFC107"
        d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"
      />
      <path
        fill="#FF3D00"
        d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"
      />
    </svg>
  );
}
