// Signed-in reads at a fixed arrival rate, judged against the SLO.
// Driven by scripts/ops/load.sh; every input comes from the environment.
//
// Arrival rate, not a fixed number of VUs: a VU that waits on a slow answer sends nothing
// meanwhile, so a closed loop slows down with the server and under-reads latency.
import exec from 'k6/execution';
import http from 'k6/http';
import { Counter } from 'k6/metrics';

const ROUTES = __ENV.ROUTES.split(',');
const RATE = Number(__ENV.RATE);
const USERS = Number(__ENV.USERS || 0);
const HEADERS = __ENV.HOST_HEADER ? { Host: __ENV.HOST_HEADER } : {};
// Seeded database: each request signs in as a random one of the seeded people.
const cookie = () => (USERS ? `load-${1 + Math.floor(Math.random() * USERS)}` : __ENV.TOKEN);

// Declared up front: k6 refuses a metric created mid-run. Anything else lands in `other`.
const KNOWN = [200, 401, 429, 500, 502, 503, 504];
const byStatus = Object.fromEntries(KNOWN.map((s) => [s, new Counter(`status_${s}`)]));
const failed = new Counter('status_none');
const other = new Counter('status_other');

const MEASURED = '{scenario:measure}';
const seconds = (d) => Number(d.replace(/s$/, ''));
const rate = (startTime, duration) => ({
  executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s', duration, startTime,
  preAllocatedVUs: RATE, maxVUs: RATE * 4,
});

// RATE, then ×3 within 10 s for 30 s, then back: does it shed with 503 and recover.
const spike = () => ({
  executor: 'ramping-arrival-rate', startRate: RATE, timeUnit: '1s',
  preAllocatedVUs: RATE * 3, maxVUs: RATE * 12,
  stages: [
    { target: RATE, duration: '30s' }, { target: RATE * 3, duration: '10s' },
    { target: RATE * 3, duration: '30s' }, { target: RATE, duration: '10s' },
    { target: RATE, duration: '60s' },
  ],
});

export const options = {
  discardResponseBodies: true,
  summaryTrendStats: ['med', 'p(95)', 'p(99)', 'max'],
  scenarios: __ENV.SHAPE === 'spike' ? { measure: spike() } : {
    // Fills the pool and the caches; not counted.
    warmup: rate('0s', __ENV.WARMUP),
    measure: rate(__ENV.WARMUP, __ENV.DURATION),
  },
  thresholds: {
    [`http_req_duration${MEASURED}`]: [`p(95)<${__ENV.SLO_P95}`, `p(99)<${__ENV.SLO_P99}`],
    [`http_req_failed${MEASURED}`]: [`rate<${__ENV.SLO_ERRORS}`],
    [`http_reqs${MEASURED}`]: ['count>0'],
    [`dropped_iterations${MEASURED}`]: ['count>=0'],
  },
};

export default function () {
  const route = ROUTES[Math.floor(Math.random() * ROUTES.length)];
  const res = http.get(__ENV.BASE + route, {
    cookies: { mycel_session: cookie() }, headers: HEADERS, timeout: '10s',
  });
  if (exec.scenario.name !== 'measure') return;
  if (res.status === 0) failed.add(1);
  else (byStatus[res.status] || other).add(1);
}

// One JSON line for load.sh: the measured window only.
export function handleSummary(data) {
  const m = (name) => data.metrics[`${name}${MEASURED}`];
  const lat = m('http_req_duration').values;
  const reqs = m('http_reqs').values;
  const dropped = m('dropped_iterations');
  const statuses = Object.fromEntries(
    Object.entries(data.metrics)
      .filter(([k, v]) => k.startsWith('status_') && v.values.count > 0)
      .map(([k, v]) => [k.slice(7), v.values.count]),
  );
  // A tagged rate divides by the whole run, warmup included; count over the window does not.
  const rps = reqs.count / seconds(__ENV.DURATION);
  // Below 95% of the asked rate means k6 ran out of VUs waiting: the server fell behind.
  const kept = rps >= RATE * 0.95;
  const ok = kept && Object.values(data.metrics).every((v) => !v.thresholds
    || Object.values(v.thresholds).every((t) => t.ok));
  const line = {
    rate: RATE, rps, p50: lat.med, p95: lat['p(95)'], p99: lat['p(99)'],
    errors: m('http_req_failed').values.rate, dropped: dropped ? dropped.values.count : 0,
    statuses, slo: ok,
  };
  return { stdout: `${JSON.stringify(line)}\n` };
}
