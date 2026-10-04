"""Tools: the capabilities an agent can call.

  compute.py        percentages, growth, basic statistics
  web_search.py     search the open web
  mail.py           read the headers of recent mail
  query.py          read gold with SQL the model wrote
  calendar.py       read the asker's calendar, and book on it after they agree
  jira.py           write to Jira as the asker, after they agree to a draft
  delegate.py       hand a question to a specialist agent
  rag_search.py     find work items by subject rather than by predicate

Each module owns its tools end to end and exports a `build_toolset()`; an agent lists the
toolsets it wants and writes no wrappers of its own. That is what makes a tool reusable:
the second agent to need one adds a line rather than copying code.

**Two error conventions, and picking the wrong one is expensive.** `compute.py` raises
`ModelRetry` because its failures are argument failures — the model can fix them by calling
again with different numbers. A tool that does I/O cannot: when a quota runs out or Qdrant is
down, re-prompting sends the model round the same loop until `max_retries` turns it into a run
error. Those raise `ToolFailed` instead.
"""
