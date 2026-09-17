"""What controllers declare via `Depends()`: auth, DB session, pagination.

**Auth lives here rather than in middleware**, because `Depends()` wins on three counts:

  - Middleware runs for *every* route, so it has to carry its own exclusion list for
    `/health`, `/docs`, `/openapi.json`. A dependency applies only where declared.
  - Dependencies reach the OpenAPI schema — `/docs` shows a padlock, and generated
    clients know a token is required.
  - A controller receives `user: User = Depends(current_user)` directly: typed, and
    checkable under mypy strict. Middleware only stuffs things into `request.state`,
    where mypy sees nothing.

A dependency answers only *who you are*; *which reports you may see* belongs to
`services/permission.py`, which needs business context the HTTP layer does not have.
"""
