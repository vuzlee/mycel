/**
 * What this is, before you have an account.
 *
 * The only page that renders signed out as well as signed in, so it takes neither the
 * `Shell` nor the `Gate`: someone arriving here may have nothing, and a rail full of
 * their runs is the wrong first screen for a person who has none.
 *
 * It says what Mycel gives you and what it costs you to get it. Not how: there are no
 * layers, agents or pipelines on this page, because a reader deciding whether they want
 * this does not yet care how it is built. `docs/architecture.html` is for that.
 */

import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import { Account } from "../components/Account";
import { Flow } from "../components/Flow";
import { ArrowRight, Mycelium } from "../components/icons";

/** Where the source and the written docs live. The API serves `/app` and nothing else,
 *  so a link to `docs/` has to leave for the repository rather than pretend to be a
 *  route here. */
const REPO = "https://github.com/vuzlee/mycel";

/** The maintainer. One address, because there is one person. */
const CONTACT = "levu040102@gmail.com";

const USES = [
  {
    when: "Monday morning",
    what: "The week, already written up",
    how: "What shipped, what is still in flight, and what is late — with the issue keys, in the words your team wrote them in.",
  },
  {
    when: "Before a stand-up",
    what: "What is past its due date",
    how: "The one thing a stand-up exists to surface, on screen before anyone speaks.",
  },
  {
    when: "End of the month",
    what: "The numbers, no writing",
    how: "Totals by status, estimated against spent per person, and effort logged per day.",
  },
];

export function Home() {
  const { user } = useAuth();

  return (
    <div className="home">
      <header>
        <span className="brand">
          <span className="mark">
            <Mycelium size={15} />
          </span>
          Mycel
        </span>

        <nav className="sections">
          <a href="#what">What you get</a>
          <a href="#ask">What it asks</a>
          <a href={`${REPO}#readme`} target="_blank" rel="noreferrer">
            Docs
          </a>
        </nav>

        {/* Signed in, the header says so plainly — and says it with the same menu the
            app's rail uses, so Profile, Settings, Help and Sign out are one click away
            from wherever someone happens to be. */}
        <nav className="account">
          {user ? (
            <>
              <Account where="bar" />
              <Link className="primary" to="/">
                Open Mycel
                <ArrowRight />
              </Link>
            </>
          ) : (
            <>
              <Link to="/login">Sign in</Link>
              <Link className="primary" to="/register">
                Create an account
                <ArrowRight />
              </Link>
            </>
          )}
        </nav>
      </header>

      <section className="lead">
        <h1>
          Your tracker already knows what happened. <em>Mycel writes it down.</em>
        </h1>
        <p>
          Nobody fills in a form and nobody chases anybody. Your team works the Jira board
          they already keep, and you ask Mycel about it in your own words.
        </p>
      </section>

      <Flow />

      <section className="uses" id="what">
        <h2 className="label">What you get</h2>
        <ol className="use-list">
          {USES.map((use) => (
            <li key={use.when}>
              <span className="when">{use.when}</span>
              <b>{use.what}</b>
              <span className="how">{use.how}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="cost" id="ask">
        <h2 className="label">What it asks of your team</h2>
        <p className="note">
          Nothing they are not already doing. Keep issues in Jira — a status, an estimate
          and a due date — and Mycel reads them. It never writes to your board: every
          answer is read-only, and nothing you ask can change the work data.
        </p>
      </section>

      <section className="named">
        <p className="aside">
          Named after <em>mycelium</em>, the underground network that connects a whole
          forest. Mycel works the same way: out of sight, quietly gathering, surfacing only
          when there is something worth surfacing.
        </p>
      </section>

      {/* The call to action, which is a different one for someone who is already here. */}
      <section className="call">
        {user ? (
          <>
            <h2>Your answers are waiting.</h2>
            <p>
              Signed in as <b>{user.email}</b>. Everything you have run is under this
              account, on any machine you sign in from.
            </p>
            <Link className="primary" to="/">
              Open Mycel
              <ArrowRight />
            </Link>
          </>
        ) : (
          <>
            <h2>Start with this week.</h2>
            <p>
              An account takes an email and a password. Your threads are kept under it, so
              they are still there on another machine tomorrow.
            </p>
            <div className="both">
              <Link className="primary" to="/register">
                Create an account
                <ArrowRight />
              </Link>
              <span>
                Already have one? <Link to="/login">Sign in</Link>
              </span>
            </div>
          </>
        )}
      </section>

      <footer>
        <div className="sig">
          <span className="brand">
            <span className="mark">
              <Mycelium size={15} />
            </span>
            Mycel
          </span>
          <p>A team's own tracked work, answered in a sentence.</p>
        </div>

        <div className="columns">
          <div>
            <span className="label">Product</span>
            <a href="#what">What you get</a>
            <a href="#ask">What it asks</a>
            {user ? (
              <Link to="/">Ask</Link>
            ) : (
              <Link to="/register">Create an account</Link>
            )}
          </div>

          <div>
            <span className="label">Project</span>
            <a href={REPO} target="_blank" rel="noreferrer">
              Source
            </a>
            <a href={`${REPO}/blob/main/docs/architecture.html`} target="_blank" rel="noreferrer">
              Architecture
            </a>
            <a href={`${REPO}/issues`} target="_blank" rel="noreferrer">
              Report a problem
            </a>
          </div>

          <div>
            <span className="label">Contact</span>
            <a href={`mailto:${CONTACT}`}>{CONTACT}</a>
            <span className="muted">Replies are from one person, so give it a day.</span>
          </div>
        </div>

        <div className="fine">
          <span>© {new Date().getFullYear()} Mycel</span>
          <span>
            Running on your own machine. Your work data stays in your database and is never
            sent anywhere but the model that answers the question.
          </span>
        </div>
      </footer>
    </div>
  );
}
