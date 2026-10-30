-- Load database at a realistic size. Run by scripts/ops/load.sh against mycel_load only.
-- psql -v users=2000 -v convs=50 -v turns=10 -v projects=20 -v items=5000
--
-- Every row is fake: lu<N>@load.invalid, projects LOAD01…, no keys, no documents' bytes.
-- Each user gets a session `load-<N>` the script hands to k6 as one cookie per VU.

\set ON_ERROR_STOP on
-- It truncates app.user: refuse any database but the load one.
select current_database() = 'mycel_load' as is_load \gset
\if :is_load
\else
  \echo refusing: seed.sql runs on mycel_load only
  \quit 3
\endif
begin;

truncate app.user, gold.work_item, gold.worklog restart identity cascade;

insert into app.user (email)
select format('lu%s@load.invalid', u) from generate_series(1, :users) u;

insert into app.session (id, user_id, expires_at)
select format('load-%s', id), id, now() + interval '1 day' from app.user;

-- Three projects a person, spread so every project has readers.
insert into app.membership (user_id, project)
select u.id, format('LOAD%s', lpad((((u.id + p) % :projects) + 1)::text, 2, '0'))
from app.user u, generate_series(0, 2) p;

insert into app.conversation (user_id, kind, title, created_at)
select u.id, 'chat', format('conversation %s', c), now() - (c || ' hours')::interval
from app.user u, generate_series(1, :convs) c;

-- Answers sized like real ones (~1.5 kB), steps left NULL as on a finished turn.
insert into app.turn (conversation_id, job_id, question, status, answer, created_at, updated_at)
select c.id, format('load-%s-%s', c.id, t), 'how is the sprint going?', 'done',
       repeat('The sprint is on track. ', 60),
       c.created_at + (t || ' minutes')::interval, c.created_at + (t || ' minutes')::interval
from app.conversation c, generate_series(1, :turns) t;

insert into app.document (user_id, filename, mime, size, sha256, object_key, status, pages)
select u.id, format('doc-%s.pdf', d), 'application/pdf', 200000, md5(u.id || '-' || d) || md5(d || '-' || u.id),
       format('load/%s/%s', u.id, d), 'ready', 12
from app.user u, generate_series(1, 5) d;

insert into gold.work_item (source, project, issue_id, issue_key, kind, title, status,
                            status_category, sprint_id, sprint_name, sprint_state,
                            original_estimate_seconds, time_spent_seconds, labels, created_at, updated_at)
select 'jira', format('LOAD%s', lpad(((i % :projects) + 1)::text, 2, '0')), i::text,
       format('LOAD%s-%s', lpad(((i % :projects) + 1)::text, 2, '0'), i),
       (array['story', 'task', 'subtask'])[(i % 3) + 1], format('work item %s', i),
       (array['To Do', 'In Progress', 'Done'])[(i % 3) + 1],
       (array['todo', 'doing', 'done'])[(i % 3) + 1],
       (i % 6) + 1, format('Sprint %s', (i % 6) + 1), case when i % 6 = 5 then 'active' else 'closed' end,
       28800, 14400 * (i % 3), '[]'::jsonb, now() - ((i % 90) || ' days')::interval, now() - ((i % 30) || ' days')::interval
from generate_series(1, :items) i;

commit;
analyze;
