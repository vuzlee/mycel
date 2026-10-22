/** What this is, before you have an account. */

import { REPO } from "../lib/links";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Account } from "../components/Account";
import { Demo } from "../components/home/Demo";
import { Flow } from "../components/home/Flow";
import { UseCases } from "../components/home/UseCases";
import { ArrowRight, Mycelium } from "../components/icons";
import { useReveal } from "../hooks/useReveal";

/** Where the source and the written docs live. The API serves `/app` and nothing else,
 *  so a link to `docs/` has to leave for the repository rather than pretend to be a
 *  route here. */

/** Four promises the code keeps, not the prompt: a claim and the words that make it checkable. */
const GUARANTEES = [
  { big: "Asks first", small: "you confirm every write" },
  { big: "Cites sources", small: "page and passage" },
  { big: "Self-hosted", small: "your data, your keys" },
  { big: "Your model", small: "or your own keys" },
];

export function Home() {
  const { user } = useAuth();
  // One ref per band that should arrive rather than simply be there. The hero is not
  // among them: it is on screen at load, and a first screen that fades in is a first
  // screen that is briefly blank.
  const guarantees = useReveal<HTMLElement>();
  const flow = useReveal<HTMLElement>();
  const uses = useReveal<HTMLElement>();
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
          <a href="#ask">Use cases</a>
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
              <Link className="primary" to="/login">
                Sign in
                <ArrowRight />
              </Link>
            </>
          )}
        </nav>
      </header>

      {/* The hero is the only place on the page with a ground of its own. It is one
          wash of the accent behind the fold, which is what makes the rest read as paper
          — a second colored band further down would make this one ordinary. */}
      <section className="lead">
        <Hyphae />
        <span className="eyebrow">
          <span className="ping" aria-hidden />
          One assistant for everything your team works in
        </span>
        <h1>
          Your work already knows what happened. <em>Mycel tells you.</em>
        </h1>
        <p>
          Ask in your own words. Mycel reads the tools your team already uses, answers with sources,
          and makes a change only once you say yes.
        </p>

        <div className="acts">
          <Link className="primary big" to={user ? "/" : "/login"}>
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

      <section className="uses" id="ask" ref={uses}>
        <h2>
          One question, <em>five places it can look</em>
        </h2>
        <UseCases />
      </section>

      {/* The call to action, which is a different one for someone who is already here. */}
      <section className="call" ref={call}>
        {user ? (
          <>
            <h2>Your answers are waiting.</h2>
            <p>
              Signed in as <b>{user.email}</b>. Everything you have run is under this account, on
              any machine you sign in from.
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
              Sign in with your account, or with a code sent to your mail. The first sign-in makes
              your account, and your conversations stay under it on every machine.
            </p>
            <div className="both">
              <Link className="primary" to="/login">
                Sign in
                <ArrowRight />
              </Link>
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
            Named after <em>mycelium</em> — the underground network that connects a whole forest.
            Out of sight, quietly gathering, surfacing only when it is worth it.
          </p>
        </div>

        <div className="columns">
          <div>
            <span className="label">Product</span>
            <a href="#what">What you get</a>
            <a href="#ask">Use cases</a>
            {user ? <Link to="/">Ask</Link> : <Link to="/login">Sign in</Link>}
          </div>

          <div>
            <span className="label">Project</span>
            <a href={REPO} target="_blank" rel="noreferrer">
              Source
            </a>
            <a
              href={`${REPO}/blob/main/docs/overview/architecture.html`}
              target="_blank"
              rel="noreferrer"
            >
              Architecture
            </a>
            <a href={`${REPO}/issues`} target="_blank" rel="noreferrer">
              Report a problem
            </a>
          </div>
        </div>

        <div className="fine">
          <span>© {new Date().getFullYear()} Mycel</span>
          <span>
            Running on your own machine. Your work data stays in your database and is never sent
            anywhere but the model that answers the question.
          </span>
        </div>
      </footer>
    </div>
  );
}

/** The mark, grown to page size, drawing itself in behind the title once. */
function Hyphae() {
  return (
    <svg className="hyphae" viewBox="0 0 800 260" aria-hidden preserveAspectRatio="none">
      <path d="M400 250V150" />
      <path d="M400 150 250 70 180 20M250 70 120 90" />
      <path d="M400 150 560 80 640 30M560 80 690 110" />
      <path d="M400 150 330 120M400 150 470 115" />
      <circle cx="400" cy="150" r="5" />
      <circle cx="180" cy="20" r="3" />
      <circle cx="640" cy="30" r="3" />
      <circle cx="120" cy="90" r="3" />
      <circle cx="690" cy="110" r="3" />
    </svg>
  );
}
