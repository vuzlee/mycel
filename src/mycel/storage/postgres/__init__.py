"""Engine, session and repositories for the raw/silver/gold layers.

  engine.py       create the engine + connection pool, DSN read from config
  session.py      a session's scope, commit/rollback
  repositories/   one repository per layer: raw, silver, gold

Keep the rule: all SQL lives in a repository. Pipelines and agents call functions with
business names; they never assemble SQL themselves.
"""
