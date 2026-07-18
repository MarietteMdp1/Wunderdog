# WonderTask — WonderDoc marketing team task management

AI-powered task management for the WonderDoc marketing team, built on the **same tech stack as
wunderdog-dashboard**: Flask + gunicorn on **Render** (auto-deploys from **GitHub**), **Supabase**
as the database, Claude for the intelligence, and all scheduled jobs running as **GitHub Actions**
— nothing runs locally.

## What it does

- **Team & roles with a skills breakdown** — Marketing Manager (admin), Content & Social Manager,
  Designer, CRM Manager seeded with editable skills lists (Admin → Roles & skills). The skills are
  what the AI matches tasks against, so the Designer never gets content tasks and vice-versa.
- **Claude AI task allocation** — analyzes **Fireflies** meeting transcripts and **Microsoft
  Teams** channel messages, extracts *real* action items only, and:
  - matches against **existing open tasks first** (your manually captured weekly-meeting tasks are
    never duplicated or overwritten — a matched item just gets a provenance comment);
  - auto-assigns only when the task's skills clearly fit a member's role **and** confidence ≥ 60%;
  - everything uncertain lands in the admin's **Needs-Allocation pool**;
  - every auto-assignment is **pending until the member accepts** (or declines back to the pool).
- **Dashboards** — the admin sees everything (all tasks, whole team, allocation pool); everyone
  else sees only their own tasks, acceptance requests, and tasks they collaborate on.
- **Collaboration** — anyone can add a teammate to a task; it then appears on that teammate's
  dashboard and board too.
- **Trello-style board** ("My Board") — every user builds their own lists, renames/deletes them,
  drags cards between lists, and opens cards for subtasks/checklist, description, due date,
  comments and collaborators. Layout is per-user: moving a card never affects a teammate's board.
- **Due dates required** on every task, with overdue/due-soon flags and an email reminder cron.

## Repo layout

```
render.yaml                     Render blueprint (web service; autoDeploy from GitHub)
.github/workflows/              ALL crons — run on GitHub, never locally
  wondertask-fireflies-sync.yml   2× daily transcript analysis
  wondertask-teams-sync.yml       3× weekdays Teams channel analysis
  wondertask-reminders.yml        weekday morning due-date reminder emails
wondertask/
  app/                          Flask app (server, AI, DB layer, static frontend)
  db/schema.sql                 Supabase schema — run once in the SQL editor
  sync_fireflies.py             cron entrypoints (also callable from Admin → "Sync now")
  sync_teams.py
  remind_due.py
```

## Setup (once)

### 1. Supabase
1. Create a Supabase project (or reuse the dashboard's project — tables are prefixed `wt_`).
2. Open **SQL Editor** and run `wondertask/db/schema.sql`.
3. Copy the **Project URL** and the **service_role key** (Settings → API).

### 2. Render
1. Merge this branch to `main`, then in Render: **New → Blueprint**, pick this GitHub repo.
   Render reads `render.yaml` and creates the `wondertask` web service (auto-deploy on push).
2. Set the secret env vars on the service: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SECRET_KEY`
   (any long random string), `ANTHROPIC_API_KEY`, `FIREFLIES_API_KEY`, and
   `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` (your first login — you'll be forced to
   change the password immediately; you can delete these two vars afterwards).
3. Optional (Teams + reminder emails): `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`
   (the same app registration as the dashboard, plus **ChannelMessage.Read.All** application
   permission for Teams and **Mail.Send** for reminders), `TEAMS_TEAM_ID`, `TEAMS_CHANNEL_ID`,
   `MAIL_SENDER`.

### 3. Custom domain (subdomain of your .com)
1. Render → the `wondertask` service → **Settings → Custom Domains → Add** e.g.
   `tasks.wunderdog.com`.
2. At your DNS provider add the **CNAME** record Render shows
   (`tasks` → `wondertask.onrender.com`). Render provisions TLS automatically.

### 4. GitHub (crons + deploys)
Deploys: nothing to do — Render auto-deploys every push to `main`.
Crons: add these **repository secrets** (Settings → Secrets and variables → Actions):
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, `FIREFLIES_API_KEY`, and for
Teams/reminders `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `TEAMS_TEAM_ID`,
`TEAMS_CHANNEL_ID`, `MAIL_SENDER`. Optionally add a repository **variable** `WONDERTASK_URL`
(e.g. `https://tasks.wunderdog.com`) used in reminder emails. Each workflow also has a manual
**Run workflow** button under the Actions tab.

### 5. Team
Log in as the bootstrap admin → **Admin → Team members** → add each member (they get a temporary
password and must change it on first login) → check **Roles & skills** and adjust the skills
lists to match how your team really splits work.

## Local development

No credentials needed — an in-memory store is seeded with demo users:

```
cd wondertask && pip install -r requirements.txt && python app/server.py
# open http://localhost:5001 — mariette@wonderdoc.com / wonder (admin)
```

## How the AI stays accurate (no garbage allocations)

1. The prompt carries the live roster with each role's skills and *instructs Claude to refuse to
   guess* — anything below 60% confidence is left unassigned.
2. Code re-checks every allocation: the named person must exist, be active, and hold exactly the
   role the AI matched; otherwise the task is pooled.
3. Every AI task carries an audit trail on the card: the matched role, confidence %, the model's
   one-line rationale, and the source meeting.
4. Duplicate protection is two-layer: Claude must match against all open tasks first, and a fuzzy
   title comparison in code catches anything it misses. Processed transcripts are remembered
   (`wt_meetings`) so a recording is never analyzed twice.
