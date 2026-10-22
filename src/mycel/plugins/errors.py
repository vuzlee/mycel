"""Errors every provider client raises."""

from mycel.core.exceptions import MycelError


class SourceError(MycelError):
    """A provider could not be reached, or answered with something unusable."""


class NotWritten(SourceError):
    """A write failed and certainly wrote nothing, so a retry is safe."""
