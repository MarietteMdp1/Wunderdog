-- WonderTask — team task management. Run once in the Supabase SQL Editor.
-- Same conventions as wunderdog-dashboard: service-key access from the app, RLS enabled on every
-- table so the anon key can never read anything. Passwords stored ONLY as salted scrypt hashes.

create extension if not exists pgcrypto;

-- Team roles with a skills breakdown. The skills list is what the AI allocator matches meeting
-- action-items against, so keep it honest: a role only receives tasks whose required skills
-- overlap its list. Seed rows are inserted by the app on first boot (editable in Admin → Roles).
create table if not exists wt_roles (
  role        text primary key,                 -- slug, e.g. 'designer'
  label       text not null,                    -- display name, e.g. 'Designer'
  description text,
  skills      jsonb not null default '[]',      -- ["graphic design","creative","branding",...]
  is_admin    boolean not null default false,   -- admin sees everything + Admin pages
  builtin     boolean not null default false,   -- seeded roles can be edited but not deleted
  created_at  timestamptz not null default now()
);
alter table wt_roles enable row level security;

create table if not exists wt_users (
  email       text primary key,
  name        text,
  role        text not null default 'viewer',
  pw_hash     text not null,
  active      boolean not null default true,
  must_change boolean not null default true,    -- force a password change on first login
  created_at  timestamptz not null default now(),
  last_login  timestamptz
);
alter table wt_users enable row level security;

create table if not exists wt_tasks (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  description text,
  due_date    date not null,                    -- every task must have a due date
  status      text not null default 'todo',     -- 'todo' | 'in_progress' | 'done'
  assignee    text,                             -- user email; NULL = needs allocation (admin pool)
  -- AI-assigned tasks must be accepted by the team member before they count as theirs.
  -- 'accepted' also covers manually created/assigned tasks (no acceptance step needed).
  acceptance  text not null default 'accepted', -- 'pending' | 'accepted' | 'declined'
  source      text not null default 'manual',   -- 'manual' | 'fireflies' | 'teams' | 'ai'
  source_ref  text,                             -- e.g. Fireflies transcript id / Teams message id
  meeting_title text,                           -- provenance shown on the card
  ai_role     text,                             -- role the AI matched (audit trail)
  ai_confidence numeric,                        -- 0..1 from the extractor
  ai_rationale  text,                           -- why the AI allocated it the way it did
  created_by  text not null,                    -- user email or 'ai'
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  completed_at timestamptz
);
alter table wt_tasks enable row level security;

-- Tasks are not done in isolation: any user can add a team member to a task; the task then also
-- appears on that member's dashboard and board.
create table if not exists wt_collaborators (
  task_id    uuid not null references wt_tasks(id) on delete cascade,
  email      text not null,
  added_by   text not null,
  created_at timestamptz not null default now(),
  primary key (task_id, email)
);
alter table wt_collaborators enable row level security;

create table if not exists wt_subtasks (
  id         uuid primary key default gen_random_uuid(),
  task_id    uuid not null references wt_tasks(id) on delete cascade,
  title      text not null,
  done       boolean not null default false,
  position   int not null default 0,
  created_at timestamptz not null default now()
);
alter table wt_subtasks enable row level security;

create table if not exists wt_comments (
  id         uuid primary key default gen_random_uuid(),
  task_id    uuid not null references wt_tasks(id) on delete cascade,
  email      text not null,                     -- 'ai' for system notes
  body       text not null,
  created_at timestamptz not null default now()
);
alter table wt_comments enable row level security;

-- Trello-style boards: each user owns their own lists (columns) and arranges cards freely.
-- Placements are PER USER — the same task can sit in different lists on different members' boards.
create table if not exists wt_lists (
  id         uuid primary key default gen_random_uuid(),
  email      text not null,                     -- board owner
  name       text not null,
  position   int not null default 0,
  created_at timestamptz not null default now()
);
alter table wt_lists enable row level security;

create table if not exists wt_placements (
  task_id    uuid not null references wt_tasks(id) on delete cascade,
  email      text not null,                     -- board owner
  list_id    uuid not null references wt_lists(id) on delete cascade,
  position   int not null default 0,
  primary key (task_id, email)
);
alter table wt_placements enable row level security;

-- Meetings already analyzed — the guard against re-processing a Fireflies recording and
-- duplicating the tasks that were entered manually in the weekly marketing meeting.
create table if not exists wt_meetings (
  id          text primary key,                 -- '<source>:<external id>'
  source      text not null,                    -- 'fireflies' | 'teams' | 'manual'
  title       text,
  meeting_date date,
  processed_at timestamptz not null default now(),
  tasks_created int not null default 0,
  tasks_matched int not null default 0
);
alter table wt_meetings enable row level security;
