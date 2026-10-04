# Tools

One-off utilities. Run when the thing they produce is out of date, not on a schedule and not
by CI.

| | |
|---|---|
| `grant_project.py` | gives someone a project — the first grant on a fresh deployment |
| `record_demo.py` | drives the real app in a browser and records the README's demo |
| `seed_jira.py` | fills an empty Jira project with this repo's own history |
| `assign_sprint.py` | drags every non-epic board issue into a sprint |

**The two Jira ones need somebody to have connected Jira first.** Since batch 060 there is
no deployment token: every call runs on one person's consent, and for a script with nobody
signed in that is the syncer's. So the order is — bring the stack up, open Settings in the
app, **Connect Jira**, then run the script. Until then they exit saying so.

That is deliberate rather than an oversight to route around. `seed_jira.py` creates issues,
and an issue created on a shared token carries the host's name whoever ran it — which Jira
cannot correct afterwards.
