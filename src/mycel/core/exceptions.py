"""Root of Mycel's exception tree."""


class MycelError(Exception):
    """Base for every error Mycel raises on purpose."""


class ConfigError(MycelError):
    """Configuration is missing or malformed: a credential, a model spec, a URL."""
