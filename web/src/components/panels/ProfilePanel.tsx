import type { ConversationSummary } from "../../api";
import { useAuth } from "../../context/auth";

/** The account, as the server knows it. The address is the identity and cannot change. */
export function ProfilePanel({ conversations }: { conversations: ConversationSummary[] }) {
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
          <dd>{conversations.length}</dd>
        </div>
        <div>
          <dt>Sign-in</dt>
          <dd>Google or emailed code</dd>
        </div>
      </dl>

      <p className="muted">
        Your runs are kept under this account, so signing in on another machine brings them with
        you. The address is the identity here and cannot be changed.
      </p>
    </>
  );
}
