import { useAuth } from "../context/auth";

/** Who is signed in is not known yet: blank while asking, a way out if the API is down. */
export function Waiting() {
  const { failed, retry } = useAuth();
  if (!failed) return <div className="waiting" />;
  return (
    <div className="waiting unreachable" role="alert">
      <p>Could not reach Mycel. It may be restarting.</p>
      <button type="button" className="primary" onClick={retry}>
        Try again
      </button>
    </div>
  );
}
