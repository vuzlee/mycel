"""Agent tools.

Argument failures raise `ModelRetry`; I/O failures raise `ToolFailed`, since re-prompting
cannot fix them.
"""
