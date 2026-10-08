import { REPO } from "../../lib/links";

const STEPS = [
  {
    title: "Keep your tracker as you already do",
    body: "Mycel reads your Jira project — issues, epics, estimates, worklogs and due dates. Nobody fills in a second form, and nothing here writes back to it.",
  },
  {
    title: "Read the week",
    body: "Ask for a project's progress over any window and it writes it up: what shipped, what is still moving, and which ticket is late.",
  },
  {
    title: "Read the numbers",
    body: "Ask for a count instead and it writes its own SQL against the work data: totals by status, estimated against spent per person, effort logged per day. Every figure comes back with the query that produced it.",
  },
  {
    title: "Ask anything else",
    body: "The same box reads your mailbox and searches the web, so a question does not have to be about your tracker to have an answer.",
  },
];

export function HelpPanel() {
  return (
    <>
      <ol className="steps">
        {STEPS.map((step) => (
          <li key={step.title}>
            <b>{step.title}</b>
            <span className="muted">{step.body}</span>
          </li>
        ))}
      </ol>

      <section>
        <h3 className="label">If something is wrong</h3>
        <p className="muted">
          Open an issue at{" "}
          <a href={`${REPO}/issues`} target="_blank" rel="noreferrer">
            the repository
          </a>
          .
        </p>
      </section>
    </>
  );
}
