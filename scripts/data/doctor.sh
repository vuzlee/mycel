#!/usr/bin/env bash
#
# What is configured, what is broken, and what is off on purpose.
#
#   scripts/stack.sh doctor
#
# The first command somebody runs after cloning, which is why it has to work with NO .env
# at all — every setting has a default, so a bare checkout still produces a report rather
# than a traceback.
#
# It writes nothing: no table, no file, no edit to .env. That is also why there is no setup
# screen — a screen has to store what it collects, and storing means configuration lives in
# two places that can disagree.
#
# Exit 1 when something is BROKEN, 0 when everything is either running or deliberately off.
# So it can gate a deploy, and so `off` never fails a build for a feature nobody wanted.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

[[ -f "$ROOT/.env" ]] || warn ".env is missing — reporting on defaults alone"

exec uv run python -c "
import asyncio, sys
from mycel.core import doctor

checks = asyncio.run(doctor.run())
print(doctor.render(checks))
sys.exit(1 if any(c.state is doctor.State.BROKEN for c in checks) else 0)
"
