#!/usr/bin/env bash
#
# Running the three app processes on the host, under pid files in .run/.
#
# Only `dev/` uses this. Compose and Kubernetes have their own supervisor and neither
# wants a pid file — which is the whole reason this is a second library rather than more
# of common.sh.
#
# Why on the host at all: these are what is being edited, and `uv run` picks up a change
# without a rebuild. That is the one thing neither of the other two modes gives.

alive() { [[ -f "$RUN/$1.pid" ]] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }

# The pid written here must be the process that actually runs, and it must be a process
# group leader — `reap` signals the whole group, because `uv run` execs a child and killing
# only the parent leaves that child alive.
#
# `setsid cmd &` gives neither. In a non-interactive shell the background job is not a
# group leader, so setsid forks: `$!` names the setsid wrapper, which exits at once. The
# pid file then holds a dead number, `alive` says stopped, and `down` kills nothing —
# which is how a machine ends up with three orphaned workers.
#
# So the inner shell writes its own `$$` and then `exec`s. After setsid it is the session
# and group leader, and `exec` means the pid does not change.
spawn() {
  local name=$1; shift
  if alive "$name"; then log "$name already up (pid $(cat "$RUN/$name.pid"))"; return; fi
  mkdir -p "$RUN"
  rm -f "${RUN:?}/${name:?}.pid"
  setsid bash -c 'echo $$ >"$1"; shift; exec "$@"' _ \
    "$RUN/$name.pid" "$@" >"$RUN/$name.log" 2>&1 </dev/null &
  disown

  # The pid file is written by a process that has not been scheduled yet.
  local pid=""
  for _ in $(seq 40); do
    [[ -s "$RUN/$name.pid" ]] && { pid=$(cat "$RUN/$name.pid"); break; }
    sleep 0.1
  done
  [[ -n $pid ]] || die "$name never started — see .run/$name.log"
  log "$name started (pid $pid, log: .run/$name.log)"
}

# Started, and still there a moment later. A process that dies on a bound port or a bad
# import exits within milliseconds, and without this the stack reports itself up while two
# thirds of it is a log file nobody reads.
settled() {
  local name=$1
  sleep 2
  alive "$name" && return 0
  printf '\033[31mxx\033[0m %s died immediately:\n' "$name" >&2
  sed 's/^/     /' "$RUN/$name.log" | tail -15 >&2
  rm -f "${RUN:?}/${name:?}.pid"
  return 1
}

reap() {
  local name=$1 pid
  alive "$name" || { rm -f "${RUN:?}/${name:?}.pid"; return; }
  pid=$(cat "$RUN/$name.pid")
  log "$name stopping (pid $pid)"
  # The group, not the process: `uv run` is a parent whose child does the work.
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  if kill -0 "$pid" 2>/dev/null; then
    log "$name ignored TERM, sending KILL"
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "${RUN:?}/${name:?}.pid"
}

# Anything of ours that no pid file points at. Earlier versions of this script wrote the
# wrong pid, and a crashed `up` can leave a half-started process behind, so `down` cannot
# assume its own bookkeeping is complete.
#
# Matched on this checkout's own interpreter path, never on the module name alone: another
# clone of this repo in another directory is somebody else's stack, and `down` here must
# not reach into it.
sweep() {
  local pids
  pids=$(pgrep -f "$ROOT/.venv/bin/.*(uvicorn|mycel\.)" 2>/dev/null || true)
  pids="$pids $(pgrep -f "^uv run .*(uvicorn --factory mycel|mycel\.queue\.consumer|mycel\.scheduler)" 2>/dev/null || true)"
  pids=$(echo "$pids" | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -un || true)
  [[ -n $pids ]] || return 0

  log "sweeping $(echo "$pids" | wc -w) stray process(es)"
  # shellcheck disable=SC2086
  kill -TERM $pids 2>/dev/null || true
  for _ in $(seq 10); do
    pgrep -f "$ROOT/.venv/bin/.*(uvicorn|mycel\.)" >/dev/null 2>&1 || break
    sleep 0.5
  done
  # shellcheck disable=SC2086
  kill -KILL $pids 2>/dev/null || true
}
