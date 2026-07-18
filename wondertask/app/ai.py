"""Claude task extraction & allocation.

Takes raw meeting material (a Fireflies transcript, Teams messages, or pasted notes) plus the
live team roster (each member's role and that role's skills) plus the currently open tasks, and
returns a structured allocation plan. Two hard rules are enforced both in the prompt and again
in code (apply_plan):

  1. Role fit — a task is only auto-assigned when its required skills clearly overlap the
     member's role skills. Anything uncertain is left unassigned and lands in the marketing
     manager's Needs-Allocation pool. Auto-assigned tasks are created with acceptance='pending'
     so the member must accept them before they count.
  2. No duplicates — Claude is given every open task and must match action items to existing
     tasks first (manually captured weekly-meeting tasks are never overwritten; a matched item
     only adds a provenance comment). A fuzzy title check in code backstops the model.
"""
import datetime as dt
import difflib
import json
import os

import db

MODEL = "claude-opus-4-8"

SCHEMA = {
    "type": "object",
    "properties": {
        "meeting_summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["new", "existing"]},
                    "existing_task_id": {"type": ["string", "null"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "role": {"type": ["string", "null"]},
                    "assignee_email": {"type": ["string", "null"]},
                    "due_date": {"type": ["string", "null"], "format": "date"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["kind", "existing_task_id", "title", "description", "role",
                             "assignee_email", "due_date", "confidence", "rationale"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["meeting_summary", "items"],
    "additionalProperties": False,
}

SYSTEM = """You extract actionable marketing tasks from meeting material for the WonderDoc team \
and allocate each one to the right team member — or to nobody, when you are not sure.

Rules, in priority order:
1. Only genuine action items. Ignore chit-chat, decisions already completed, and vague intentions \
with no owner-able action. Fewer accurate tasks beat many noisy ones.
2. Match to EXISTING tasks first. You are given every open task. If an action item is the same \
piece of work as an open task (even worded differently), return kind="existing" with that task's \
id — never a duplicate. Manually captured tasks from the weekly marketing meeting must never be \
recreated.
3. Role fit is strict. Each member's role lists its skills. Assign a task only when its required \
skills clearly overlap the role's skills: content/copy/social work never goes to the Designer; \
creative/design work never goes to the Content & Social Manager; CRM/HubSpot/campaign-workflow \
work goes to the CRM Manager, never content work. If the meeting explicitly names a person for a \
task, that overrides skill inference ONLY if the work plausibly fits their role.
4. When unsure, don't guess. Set assignee_email and role to null with confidence below 0.6 — the \
marketing manager will allocate it by hand. A wrong allocation is worse than no allocation.
5. Every new task needs a due date. Use one stated in the meeting; otherwise infer a sensible \
date from context/urgency; otherwise null (the system will default it).
6. confidence is YOUR certainty (0-1) that the task is real AND correctly allocated. rationale is \
one sentence the marketing manager reads to audit your decision."""


def _client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set — add it in Render (web service) and "
                           "GitHub repo secrets (crons) to enable AI task extraction.")
    import anthropic
    return anthropic.Anthropic()


def _roster_block():
    users = [u for u in db.select("wt_users") if u.get("active")]
    role_map = {r["role"]: r for r in db.select("wt_roles")}
    lines = []
    for u in users:
        r = role_map.get(u.get("role"), {})
        skills = ", ".join(r.get("skills") or []) or "(no listed skills — never auto-assign)"
        lines.append(f"- {u.get('name') or u['email']} <{u['email']}> — role: "
                     f"{r.get('label', u.get('role'))} ({u.get('role')}). Skills: {skills}")
    return "\n".join(lines) or "(no team members registered yet)"


def _open_tasks():
    return [t for t in db.select("wt_tasks", order="created_at.desc", limit=400)
            if t.get("status") != "done"]


def _open_tasks_block(tasks):
    lines = []
    for t in tasks:
        lines.append(f"- id={t['id']} | \"{t['title']}\" | assignee={t.get('assignee') or 'none'} "
                     f"| due={t.get('due_date')} | source={t.get('source')}")
    return "\n".join(lines) or "(no open tasks)"


def extract(text, meeting_title="", meeting_date=None):
    """Run Claude over meeting material. Returns the parsed plan dict (see SCHEMA)."""
    client = _client()
    open_tasks = _open_tasks()
    today = dt.date.today().isoformat()
    prompt = (
        f"Today's date: {today}\n"
        f"Meeting: {meeting_title or 'untitled'} on {meeting_date or 'unknown date'}\n\n"
        f"TEAM ROSTER (roles and skills):\n{_roster_block()}\n\n"
        f"OPEN TASKS (match against these before creating anything new):\n"
        f"{_open_tasks_block(open_tasks)}\n\n"
        f"MEETING MATERIAL:\n{text[:150000]}"
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined to process this material.")
    body = next(b.text for b in resp.content if b.type == "text")
    plan = json.loads(body)
    plan["_open_tasks"] = open_tasks
    return plan


def _fuzzy_match(title, open_tasks):
    """Backstop: catch near-duplicate titles the model called 'new'."""
    for t in open_tasks:
        ratio = difflib.SequenceMatcher(None, title.lower(), (t.get("title") or "").lower()).ratio()
        if ratio >= 0.85:
            return t
    return None


def apply_plan(plan, source, source_ref, meeting_title="", meeting_date=None):
    """Write the plan to the database. Returns a summary dict for the UI / cron log."""
    open_tasks = plan.get("_open_tasks") or _open_tasks()
    by_id = {t["id"]: t for t in open_tasks}
    users = {u["email"]: u for u in db.select("wt_users")}
    role_map = {r["role"]: r for r in db.select("wt_roles")}
    created, matched, pooled = [], [], []

    for item in plan.get("items", []):
        title = (item.get("title") or "").strip()
        if not title:
            continue
        existing = by_id.get(item.get("existing_task_id")) if item.get("kind") == "existing" else None
        if not existing:
            existing = _fuzzy_match(title, open_tasks)
        if existing:
            # Never overwrite an existing (e.g. manually captured) task — only add provenance.
            db.insert("wt_comments", {
                "task_id": existing["id"], "email": "ai",
                "body": f"Also raised in \"{meeting_title or source}\" "
                        f"({meeting_date or 'date unknown'}): {item.get('rationale') or title}"})
            matched.append({"task_id": existing["id"], "title": existing["title"]})
            continue

        assignee = item.get("assignee_email")
        confidence = float(item.get("confidence") or 0)
        role_slug = (item.get("role") or "").lower() or None
        user = users.get(assignee) if assignee else None
        # Code-level guard: the named person must exist, be active, and their actual role must be
        # the role the AI matched. Any mismatch → Needs-Allocation pool, never a wrong assignment.
        ok = bool(user and user.get("active") and confidence >= 0.6
                  and role_slug and user.get("role") == role_slug
                  and (role_map.get(role_slug, {}).get("skills")))
        due = item.get("due_date")
        if not due:
            base = None
            try:
                base = dt.date.fromisoformat(str(meeting_date)[:10]) if meeting_date else None
            except ValueError:
                base = None
            due = ((base or dt.date.today()) + dt.timedelta(days=7)).isoformat()

        task = db.insert("wt_tasks", {
            "title": title[:300],
            "description": item.get("description") or "",
            "due_date": due,
            "status": "todo",
            "assignee": assignee if ok else None,
            "acceptance": "pending" if ok else "accepted",
            "source": source,
            "source_ref": source_ref,
            "meeting_title": meeting_title,
            "ai_role": role_slug,
            "ai_confidence": confidence,
            "ai_rationale": item.get("rationale") or "",
            "created_by": "ai",
        })
        (created if ok else pooled).append({"task_id": task.get("id"), "title": title,
                                            "assignee": assignee if ok else None})

    if source_ref:
        db.upsert("wt_meetings", {
            "id": f"{source}:{source_ref}", "source": source, "title": meeting_title,
            "meeting_date": (str(meeting_date)[:10] if meeting_date else None),
            "tasks_created": len(created) + len(pooled), "tasks_matched": len(matched)})

    return {"summary": plan.get("meeting_summary", ""), "assigned": created,
            "needs_allocation": pooled, "matched_existing": matched}


def already_processed(source, source_ref):
    return bool(db.select("wt_meetings", eq={"id": f"{source}:{source_ref}"}))


def analyze(text, source="manual", source_ref=None, meeting_title="", meeting_date=None):
    """extract + apply in one call — used by the admin UI and the sync crons."""
    plan = extract(text, meeting_title=meeting_title, meeting_date=meeting_date)
    return apply_plan(plan, source, source_ref, meeting_title=meeting_title,
                      meeting_date=meeting_date)
