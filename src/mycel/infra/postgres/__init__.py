"""Engine, session, models and repositories for the bronze/silver/gold layers.

  engine.py       the process-wide engine, DSN read from config
  session.py      a session's scope: commit, rollback, close
  models.py       the mapped tables; alembic autogenerates against this metadata
  repositories/   one per layer: bronze, silver, gold

All SQL lives in a repository. Pipelines and agents call functions with business names;
they never assemble SQL themselves. Migrations live in `migrations/`, outside the package,
because they are applied by a command rather than imported by code.
"""
