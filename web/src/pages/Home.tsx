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
 *
 * The page shows the product before it describes it. `Demo` runs a scripted question at
 * the top, because the fastest way to answer "what is this" is to let someone watch one
 * question go in and an answer come out, and every sentence after it is then a caption
 * on something already seen rather than a claim taken on trust.
 *
 * Motion is a reveal on scroll and nothing else. Nothing moves that a reader did not
 * scroll to, nothing loops except the demo, and every animation is an offset being
 * removed — so the page is complete and readable with no JavaScript and with reduced
 * motion on.
 */

import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import { Account } from "../components/Account";
import { Demo } from "../components/Demo";
import { Flow } from "../components/Flow";
import { ArrowRight, Mycelium } from "../components/icons";
import { useReveal } from "../useReveal";

/** Where the source and the written docs live. The API serves `/app` and nothing else,
 *  so a link to `docs/` has to leave for the repository rather than pretend to be a
 *  route here. */
const REPO = "https://github.com/vuzlee/mycel";

/** The maintainer. One address, because there is one person. */
const CONTACT = "levu040102@gmail.com";

/** Three moments, not three features. Each is one line of prose and one line someone
 *  would actually type — an earlier version carried a third sentence explaining the
 *  first, which is how a page ends up with more words than a reader has patience. */
const USES = [
  {
    when: "Monday",
    what: "The week, already written up",
    ask: "How is MYC going this week?",
  },
  {
    when: "Stand-up",
    what: "What is past its due date",
    ask: "What is late right now, and who is it with?",
  },
  {
    when: "Month end",
    what: "The numbers, no writing",
    ask: "Compare hours logged with last month.",
  },
];

/** Four promises the code keeps, not the prompt. An earlier version gave each one a
 *  sentence, and four sentences in a row is a paragraph nobody reads — so each is now a
 *  claim and the three words that make it checkable. */
const GUARANTEES = [
  { big: "Read-only", small: "enforced by Postgres" },
  { big: "Self-hosted", small: "your database, your keys" },
  { big: "No new habits", small: "the board you already keep" },
  { big: "One command", small: "the whole stack, up" },
];

export function Home() {
  const { user } = useAuth();
  // One ref per band that should arrive rather than simply be there. The hero is not
  // among them: it is on screen at load, and a first screen that fades in is a first
  // screen that is briefly blank.
  const guarantees = useReveal<HTMLElement>();
  const flow = useReveal<HTMLElement>();
  const uses = useReveal<HTMLElement>();
  const cost = useReveal<HTMLElement>();
  const call = useReveal<HTMLElement>();

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

      {/* The hero is the only place on the page with a ground of its own. It is one
          wash of the accent behind the fold, which is what makes the rest read as paper
          — a second coloured band further down would make this one ordinary. */}
      <section className="lead">
        <span className="eyebrow">
          <span className="ping" aria-hidden />
          Reads your board. Never writes to it.
        </span>
        <h1>
          Your tracker already knows what happened. <em>Mycel writes it down.</em>
        </h1>
        <p>
          Nobody fills in a form and nobody chases anybody. Your team works the Jira board
          they already keep, and you ask Mycel about it in your own words.
        </p>

        <div className="acts">
          <Link className="primary big" to={user ? "/" : "/register"}>
            {user ? "Open Mycel" : "Start with this week"}
            <ArrowRight />
          </Link>
          <a className="ghost" href={`${REPO}#readme`} target="_blank" rel="noreferrer">
            Read the source
          </a>
        </div>

        <Demo />
      </section>

      {/* A thin band of what the code guarantees, between the demo and the prose. It is
          the answer to the question a reader has the moment the demo ends — what is this
          allowed to do to my board — and it belongs before the features, not after. */}
      <section className="guarantees" ref={guarantees}>
        {GUARANTEES.map((item) => (
          <div key={item.big}>
            <b>{item.big}</b>
            <span>{item.small}</span>
          </div>
        ))}
      </section>

      <section className="band" id="what" ref={flow}>
        <h2>
          Ask in a sentence. <em>Get a dashboard.</em>
        </h2>
        <Flow />
      </section>

      <section className="uses" ref={uses}>
        <h2>
          Three moments <em>it earns its keep</em>
        </h2>
        <ol className="use-list">
          {USES.map((use) => (
            <li key={use.when}>
              <span className="when">{use.when}</span>
              <b>{use.what}</b>
              {/* The words someone would actually type. A feature list says what a
                  product does; this says what you do. */}
              <span className="ask">{use.ask}</span>
            </li>
          ))}
        </ol>
      </section>

      {/* What it costs, as three things a team already has. Prose here was two blocks of
          grey text saying "nothing changes", which is a claim a list makes faster. */}
      <section className="cost" id="ask" ref={cost}>
        <h2>
          It asks your team <em>for nothing</em>
        </h2>
        <ul className="already">
          <li>
            <b>A status</b>
            <span>To do, in progress, done</span>
          </li>
          <li>
            <b>An estimate</b>
            <span>However rough</span>
          </li>
          <li>
            <b>A due date</b>
            <span>When it is meant to land</span>
          </li>
        </ul>
        <p className="note">
          That is the whole contract. Mycel reads the board and never writes to it.
        </p>
      </section>

      {/* The call to action, which is a different one for someone who is already here. */}
      <section className="call" ref={call}>
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
          {/* The naming story lives here rather than in a band of its own: it explains
              the word on the tab, which is a thing you look up, not a thing you are sold. */}
          <p>
            Named after <em>mycelium</em> — the underground network that connects a whole
            forest. Out of sight, quietly gathering, surfacing only when it is worth it.
          </p>
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
