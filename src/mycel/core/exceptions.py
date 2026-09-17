"""The base of Mycel's exception tree.

One root so layers above can catch by group without knowing the details: `api/` turns any
`MycelError` into a 4xx/5xx it understands, and anything that is *not* a `MycelError` is a
bug rather than a handled condition.

Each package adds its own branch — `agents/core/exceptions.py` has the agent ones.
"""


class MycelError(Exception):
    """Base for every error Mycel raises on purpose."""


class ConfigError(MycelError):
    """Configuration is missing or malformed — a credential, a model spec, a URL.

    Raised at startup or at first use, never swallowed: running with half a configuration
    fails later and further from the cause.
    """
