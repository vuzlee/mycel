"""Can this person see this project.

The data is a team's own tracked work, so permission is checked before touching gold — not
after an answer has already been produced from it.

Today there is one rule and it is "yes, if you are logged in": there is no membership
table to consult, and inventing one that always answers true would be the same rule with
more code. What matters is that the *call site* is already right — every place that reads
one project's data asks this function first, so the day a rule exists it is added here and
nowhere else.
"""

from mycel.services.auth import Principal


async def can_read_project(user: Principal, project: str) -> bool:
    """Whether this person may read this project's work.

    Any authenticated user may read any project. Deliberate and temporary: this runs for
    one team on one machine. The signature already carries what a real rule needs.
    """
    return True
