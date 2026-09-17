"""Health checks.

  /health/live   — is the process alive. Used by the restart policy.
  /health/ready  — is it ready to take requests (DB reachable, migrations applied).
                   Used by the load balancer, to avoid sending traffic to an instance
                   that is not ready yet.
"""
