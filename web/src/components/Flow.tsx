/**
 * What Mycel does, drawn once.
 *
 * The left is the tracker a team already keeps — three issues, each with a key, a status
 * and a due date. The right is what comes back. Nothing in between is named, because how
 * it gets there is not the reader's problem on a page that is asking them whether they
 * want this at all.
 *
 * Drawn rather than screenshotted: a screenshot is out of date the next time the layout
 * moves, and at this size it would be unreadable anyway.
 */

const TRACKED = [
  { key: "MYC-14", category: "done", text: "migration merged" },
  { key: "MYC-17", category: "doing", text: "dashboard, 2d of 3d spent" },
  { key: "MYC-21", category: "late", text: "due Friday, not started" },
];

export function Flow() {
  return (
    <div className="flow" aria-hidden>
      <div className="posted">
        {TRACKED.map((line) => (
          <div className="bubble" key={line.key}>
            <span className="tag" data-tag={line.category}>
              {line.key}
            </span>
            <span className="said">{line.text}</span>
          </div>
        ))}
        <span className="caption">what your tracker already holds</span>
      </div>

      <svg className="link" viewBox="0 0 64 120" fill="none" aria-hidden>
        <path d="M0 60H26" />
        <path d="M38 60h26M38 60 26 28h38M38 60l-12 32h38" className="fan" />
        <circle cx="32" cy="60" r="5" className="node" />
      </svg>

      <div className="produced">
        <article className="sheet">
          <span className="label">Progress report</span>
          <span className="line" style={{ width: "88%" }} />
          <span className="line" style={{ width: "64%" }} />
          <span className="line" style={{ width: "76%" }} />
          <span className="line faint" style={{ width: "42%" }} />
        </article>

        <article className="sheet">
          <span className="label">Dashboard</span>
          <div className="bars">
            <span data-tag="done" style={{ height: "80%" }} />
            <span data-tag="doing" style={{ height: "52%" }} />
            <span data-tag="todo" style={{ height: "40%" }} />
            <span data-tag="late" style={{ height: "28%" }} />
          </div>
        </article>
        <span className="caption">what you read on Monday</span>
      </div>
    </div>
  );
}
