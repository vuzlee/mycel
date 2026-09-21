/**
 * Create an account — and stop there.
 *
 * `POST /auth/register` issues no cookie, so a new account is not a signed-in one. The
 * page says so and sends you to the login form, which is where the password gets proved
 * rather than assumed.
 *
 * Registration is open: anyone who can reach this page can create an account. That is
 * fine for a machine on a desk and is the first thing to revisit if this is ever exposed.
 */

import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { register } from "../api";
import { useAuth } from "../auth";
import { Credentials } from "../components/Credentials";
import { Mycelium } from "../components/icons";

export function Register() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [failure, setFailure] = useState<string | null>(null);

  // Already signed in: there is nothing to create.
  if (user) return <Navigate to="/" replace />;

  const create = async (email: string, password: string): Promise<void> => {
    await register(email, password);
    navigate("/login", {
      replace: true,
      state: { notice: `Account created for ${email}. Sign in to start.` },
    });
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

        <h1>Create an account</h1>
        <p className="lede">
          Your runs and saved reports live under it, so they are still there on another
          machine tomorrow.
        </p>

        <Credentials
          verb="Create account"
          isNew
          onSubmit={create}
          failure={failure}
          onFailure={setFailure}
        />

        <p className="switch">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
