// Signed-in reads at a constant number of virtual users, counted by status.
// Driven by scripts/ops/load.sh; every input comes from the environment.
import http from 'k6/http';
import { Counter } from 'k6/metrics';

const ROUTES = __ENV.ROUTES.split(',');
const PARAMS = {
  cookies: { mycel_session: __ENV.TOKEN },
  headers: __ENV.HOST_HEADER ? { Host: __ENV.HOST_HEADER } : {},
  timeout: '30s',
};

// Declared up front: k6 refuses a metric created mid-run. Anything else lands in `other`.
const KNOWN = [200, 401, 429, 500, 502, 503, 504];
const byStatus = Object.fromEntries(KNOWN.map((s) => [s, new Counter(`status_${s}`)]));
const failed = new Counter('status_none');
const other = new Counter('status_other');

export const options = {
  discardResponseBodies: true,
  scenarios: { reads: { executor: 'constant-vus', vus: Number(__ENV.VUS), duration: __ENV.DURATION } },
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const route = ROUTES[Math.floor(Math.random() * ROUTES.length)];
  const res = http.get(__ENV.BASE + route, PARAMS);
  if (res.status === 0) failed.add(1);
  else (byStatus[res.status] || other).add(1);
}
