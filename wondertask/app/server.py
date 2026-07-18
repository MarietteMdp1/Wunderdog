"""WonderTask web service — Flask app served by gunicorn on Render (same shape as
wunderdog-dashboard: session-cookie auth, per-user accounts in Supabase, service-key data access,
/healthz open for Render health checks).

Local dev: run `python app/server.py` with no env vars — an in-memory store is seeded with the
WonderDoc roles and demo users (password "wonder" for all), so every screen works offline.
Production bootstrap: set BOOTSTRAP_ADMIN_EMAIL + BOOTSTRAP_ADMIN_PASSWORD once; the first boot
creates the admin account (with a forced password change) and the built-in roles.
"""
import datetime as dt
import functools
import logging
import os
import pathlib
import secrets as pysecrets

from flask import Flask, g, jsonify, redirect, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import ai
import db
import integrations
import roles as roles_mod
import ui

BASE = pathlib.Path(__file__).parent
app = Flask(__name__, static_folder=str(BASE / "static"))
app.secret_key = os.environ.get("SECRET_KEY") or pysecrets.token_hex(32)
app.permanent_session_lifetime = dt.timedelta(days=14)
log = logging.getLogger("wondertask")

OPEN_PATHS = {"/login", "/healthz"}
DEFAULT_LISTS = ["To Do", "Doing", "Done"]


# ---------------- bootstrap ----------------

def bootstrap():
    roles_mod.ensure_seed()
    if db.select("wt_users", limit=1):
        return
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    pw = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    if email and pw:
        db.insert("wt_users", {"email": email, "name": "Marketing Manager",
                               "role": "marketing_manager",
                               "pw_hash": generate_password_hash(pw), "must_change": True})
        log.info("bootstrapped admin user %s", email)
    elif not db.HAS_DB:  # local dev — demo team, password "wonder"
        demo = [("mariette@wonderdoc.com", "Mariette", "marketing_manager"),
                ("content@wonderdoc.com", "Casey Content", "content_social"),
                ("design@wonderdoc.com", "Dana Designer", "designer"),
                ("crm@wonderdoc.com", "Chris CRM", "crm_manager")]
        for email_, name, role in demo:
            db.insert("wt_users", {"email": email_, "name": name, "role": role,
                                   "pw_hash": generate_password_hash("wonder"),
                                   "must_change": False})
        due = (dt.date.today() + dt.timedelta(days=5)).isoformat()
        t = db.insert("wt_tasks", {"title": "Plan August social calendar",
                                   "description": "Draft the content calendar for August.",
                                   "due_date": due, "assignee": "content@wonderdoc.com",
                                   "created_by": "mariette@wonderdoc.com"})
        db.insert("wt_subtasks", {"task_id": t["id"], "title": "Collect campaign dates"})
        db.insert("wt_tasks", {"title": "New homepage hero banner",
                               "description": "Creative refresh for the homepage hero.",
                               "due_date": due, "assignee": "design@wonderdoc.com",
                               "acceptance": "pending", "source": "fireflies",
                               "meeting_title": "Weekly marketing meeting",
                               "ai_role": "designer", "ai_confidence": 0.82,
                               "ai_rationale": "Creative/banner work fits the Designer role.",
                               "created_by": "ai"})
        db.insert("wt_tasks", {"title": "Investigate TikTok advertising options",
                               "description": "Raised in the weekly meeting; owner unclear.",
                               "due_date": due, "assignee": None, "source": "fireflies",
                               "meeting_title": "Weekly marketing meeting",
                               "ai_confidence": 0.4,
                               "ai_rationale": "No role clearly owns paid TikTok exploration.",
                               "created_by": "ai"})


bootstrap()


# ---------------- auth ----------------

def get_user(email):
    rows = db.select("wt_users", eq={"email": (email or "").lower()})
    return rows[0] if rows else None


def role_info(user):
    r = roles_mod.get(user.get("role")) or {}
    return {"role_label": r.get("label", user.get("role")),
            "is_admin": bool(r.get("is_admin"))}


@app.before_request
def require_login():
    p = request.path
    if p in OPEN_PATHS or p.startswith("/static/"):
        return None
    email = session.get("user")
    user = get_user(email) if email else None
    if not user or not user.get("active"):
        if p.startswith("/api/"):
            return jsonify({"error": "not signed in"}), 401
        return redirect("/login")
    g.user = user
    g.perms = role_info(user)
    if user.get("must_change") and p not in ("/account", "/logout"):
        return redirect("/account")
    return None


def admin_only(fn):
    @functools.wraps(fn)
    def wrap(*a, **kw):
        if not g.perms["is_admin"]:
            return jsonify({"error": "admin only"}), 403
        return fn(*a, **kw)
    return wrap


@app.get("/healthz")
def healthz():
    return "ok"


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        user = get_user(email)
        if user and user.get("active") and check_password_hash(user.get("pw_hash", ""), pw):
            session.permanent = True
            session["user"] = email
            db.update("wt_users", {"email": email},
                      {"last_login": dt.datetime.now(dt.timezone.utc).isoformat()})
            return redirect("/")
        error = '<p class="error">Wrong email or password.</p>'
    return ui.LOGIN.format(error=error)


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/account", methods=["GET", "POST"])
def account():
    notice = ""
    if g.user.get("must_change"):
        notice = '<p class="notice">Please set a new password before continuing.</p>'
    if request.method == "POST":
        cur, new, new2 = (request.form.get(k, "") for k in ("current", "new", "new2"))
        if not check_password_hash(g.user.get("pw_hash", ""), cur):
            notice = '<p class="error">Current password is wrong.</p>'
        elif new != new2:
            notice = '<p class="error">New passwords do not match.</p>'
        elif len(new) < 8:
            notice = '<p class="error">New password must be at least 8 characters.</p>'
        else:
            db.update("wt_users", {"email": g.user["email"]},
                      {"pw_hash": generate_password_hash(new), "must_change": False})
            return redirect("/")
    body = ui.ACCOUNT.format(notice=notice)
    return ui.page("Account", "account", body, "", g.user, g.perms["is_admin"])


# ---------------- pages ----------------

@app.get("/")
def dashboard_page():
    return ui.page("Dashboard", "dashboard", '<div id="dash" class="loading">Loading…</div>',
                   '<script src="/static/common.js"></script><script src="/static/app.js"></script>',
                   {**g.user, **g.perms}, g.perms["is_admin"])


@app.get("/board")
def board_page():
    return ui.page("My Board", "board", '<div id="board" class="loading">Loading…</div>',
                   '<script src="/static/common.js"></script><script src="/static/board.js"></script>',
                   {**g.user, **g.perms}, g.perms["is_admin"])


@app.get("/admin")
@admin_only
def admin_page():
    return ui.page("Admin", "admin", '<div id="admin" class="loading">Loading…</div>',
                   '<script src="/static/common.js"></script><script src="/static/admin.js"></script>',
                   {**g.user, **g.perms}, True)


# ---------------- task helpers ----------------

def task_visible(t, email, is_admin, collab_ids):
    if is_admin:
        return True
    return t.get("assignee") == email or t.get("created_by") == email or t["id"] in collab_ids


def my_collab_ids(email):
    return {c["task_id"] for c in db.select("wt_collaborators", eq={"email": email})}


def can_edit(t):
    if g.perms["is_admin"] or t.get("assignee") == g.user["email"] \
            or t.get("created_by") == g.user["email"]:
        return True
    return bool(db.select("wt_collaborators",
                          eq={"task_id": t["id"], "email": g.user["email"]}))


def enrich(tasks):
    """Attach collaborators + subtask counts for card rendering."""
    ids = [t["id"] for t in tasks]
    collabs, subs = {}, {}
    if ids:
        for c in db.select("wt_collaborators", in_={"task_id": ids}):
            collabs.setdefault(c["task_id"], []).append(c["email"])
        for s in db.select("wt_subtasks", in_={"task_id": ids}):
            d = subs.setdefault(s["task_id"], {"total": 0, "done": 0})
            d["total"] += 1
            d["done"] += 1 if s.get("done") else 0
    users = {u["email"]: (u.get("name") or u["email"]) for u in db.select("wt_users")}
    for t in tasks:
        t["collaborators"] = collabs.get(t["id"], [])
        t["subtasks"] = subs.get(t["id"], {"total": 0, "done": 0})
        t["assignee_name"] = users.get(t.get("assignee"), t.get("assignee"))
    return tasks


def get_task_or_404(tid):
    rows = db.select("wt_tasks", eq={"id": tid})
    return rows[0] if rows else None


# ---------------- core APIs ----------------

@app.get("/api/me")
def api_me():
    return jsonify({"email": g.user["email"], "name": g.user.get("name"),
                    "role": g.user.get("role"), **g.perms})


@app.get("/api/team")
def api_team():
    role_map = roles_mod.all_roles()
    out = [{"email": u["email"], "name": u.get("name") or u["email"],
            "role": u.get("role"),
            "role_label": role_map.get(u.get("role"), {}).get("label", u.get("role"))}
           for u in db.select("wt_users") if u.get("active")]
    return jsonify(out)


@app.get("/api/tasks")
def api_tasks():
    email = g.user["email"]
    is_admin = g.perms["is_admin"]
    collab_ids = my_collab_ids(email)
    tasks = db.select("wt_tasks", order="due_date.asc", limit=1000)
    mine = [t for t in tasks if t.get("assignee") == email and t.get("acceptance") == "accepted"]
    pending = [t for t in tasks if t.get("assignee") == email
               and t.get("acceptance") == "pending"]
    collaborating = [t for t in tasks if t["id"] in collab_ids and t.get("assignee") != email]
    out = {"mine": enrich(mine), "pending": enrich(pending),
           "collaborating": enrich(collaborating)}
    if is_admin:
        out["needs_allocation"] = enrich([t for t in tasks if not t.get("assignee")
                                          and t.get("status") != "done"])
        out["all"] = enrich(list(tasks))
    return jsonify(out)


@app.post("/api/tasks")
def api_create_task():
    b = request.get_json(force=True)
    title = (b.get("title") or "").strip()
    due = (b.get("due_date") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    if not due:
        return jsonify({"error": "a due date is required — every task must have one"}), 400
    assignee = (b.get("assignee") or "").strip().lower() or None
    if assignee and not get_user(assignee):
        return jsonify({"error": f"unknown assignee {assignee}"}), 400
    task = db.insert("wt_tasks", {
        "title": title[:300], "description": b.get("description") or "",
        "due_date": due, "assignee": assignee,
        # assigning someone else's work still needs their acceptance; own tasks are auto-accepted
        "acceptance": "accepted" if (not assignee or assignee == g.user["email"]) else "pending",
        "source": "manual", "created_by": g.user["email"]})
    for email in b.get("collaborators") or []:
        if get_user(email):
            db.insert("wt_collaborators", {"task_id": task["id"], "email": email.lower(),
                                           "added_by": g.user["email"]})
    return jsonify(task), 201


@app.get("/api/tasks/<tid>")
def api_task_detail(tid):
    t = get_task_or_404(tid)
    if not t:
        return jsonify({"error": "not found"}), 404
    if not task_visible(t, g.user["email"], g.perms["is_admin"], my_collab_ids(g.user["email"])):
        return jsonify({"error": "forbidden"}), 403
    enrich([t])
    t["subtask_rows"] = sorted(db.select("wt_subtasks", eq={"task_id": tid}),
                               key=lambda s: (s.get("position", 0), s.get("created_at") or ""))
    t["comments"] = db.select("wt_comments", eq={"task_id": tid}, order="created_at.asc")
    t["can_edit"] = can_edit(t)
    return jsonify(t)


@app.patch("/api/tasks/<tid>")
def api_update_task(tid):
    t = get_task_or_404(tid)
    if not t:
        return jsonify({"error": "not found"}), 404
    if not can_edit(t):
        return jsonify({"error": "forbidden"}), 403
    b = request.get_json(force=True)
    patch = {}
    for k in ("title", "description", "due_date", "status"):
        if k in b and b[k] is not None:
            patch[k] = b[k]
    if "assignee" in b:  # reassignment: admin anywhere; anyone may claim an unassigned task
        new_assignee = (b.get("assignee") or "").strip().lower() or None
        if not (g.perms["is_admin"] or (t.get("assignee") is None
                                        and new_assignee == g.user["email"])):
            return jsonify({"error": "only an admin can reassign tasks"}), 403
        if new_assignee and not get_user(new_assignee):
            return jsonify({"error": "unknown assignee"}), 400
        patch["assignee"] = new_assignee
        patch["acceptance"] = "accepted" if new_assignee == g.user["email"] else "pending"
    if patch.get("status") == "done":
        patch["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    if patch.get("due_date") == "":
        return jsonify({"error": "a due date is required"}), 400
    patch["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    out = db.update("wt_tasks", {"id": tid}, patch)
    return jsonify(out[0] if out else {})


@app.delete("/api/tasks/<tid>")
def api_delete_task(tid):
    t = get_task_or_404(tid)
    if not t:
        return jsonify({"error": "not found"}), 404
    if not (g.perms["is_admin"] or t.get("created_by") == g.user["email"]):
        return jsonify({"error": "only the creator or an admin can delete a task"}), 403
    for table in ("wt_subtasks", "wt_comments", "wt_collaborators", "wt_placements"):
        db.delete(table, {"task_id": tid})
    db.delete("wt_tasks", {"id": tid})
    return jsonify({"ok": True})


@app.post("/api/tasks/<tid>/accept")
def api_accept(tid):
    t = get_task_or_404(tid)
    if not t or t.get("assignee") != g.user["email"]:
        return jsonify({"error": "not your task"}), 403
    db.update("wt_tasks", {"id": tid}, {"acceptance": "accepted"})
    db.insert("wt_comments", {"task_id": tid, "email": g.user["email"],
                              "body": "Accepted this task."})
    return jsonify({"ok": True})


@app.post("/api/tasks/<tid>/decline")
def api_decline(tid):
    t = get_task_or_404(tid)
    if not t or t.get("assignee") != g.user["email"]:
        return jsonify({"error": "not your task"}), 403
    reason = (request.get_json(silent=True) or {}).get("reason", "")
    db.update("wt_tasks", {"id": tid}, {"assignee": None, "acceptance": "accepted"})
    db.delete("wt_placements", {"task_id": tid, "email": g.user["email"]})
    db.insert("wt_comments", {"task_id": tid, "email": g.user["email"],
                              "body": f"Declined this task. {('Reason: ' + reason) if reason else ''}".strip()})
    return jsonify({"ok": True})


@app.post("/api/tasks/<tid>/collaborators")
def api_add_collab(tid):
    t = get_task_or_404(tid)
    if not t:
        return jsonify({"error": "not found"}), 404
    if not can_edit(t):
        return jsonify({"error": "forbidden"}), 403
    email = ((request.get_json(force=True).get("email")) or "").strip().lower()
    if not get_user(email):
        return jsonify({"error": "unknown user"}), 400
    if email == t.get("assignee"):
        return jsonify({"error": "already the assignee"}), 400
    if not db.select("wt_collaborators", eq={"task_id": tid, "email": email}):
        db.insert("wt_collaborators", {"task_id": tid, "email": email,
                                       "added_by": g.user["email"]})
        db.insert("wt_comments", {"task_id": tid, "email": g.user["email"],
                                  "body": f"Added {email} as a collaborator."})
    return jsonify({"ok": True})


@app.delete("/api/tasks/<tid>/collaborators/<email>")
def api_del_collab(tid, email):
    t = get_task_or_404(tid)
    if not t or not can_edit(t):
        return jsonify({"error": "forbidden"}), 403
    db.delete("wt_collaborators", {"task_id": tid, "email": email.lower()})
    db.delete("wt_placements", {"task_id": tid, "email": email.lower()})
    return jsonify({"ok": True})


@app.post("/api/tasks/<tid>/subtasks")
def api_add_subtask(tid):
    t = get_task_or_404(tid)
    if not t or not can_edit(t):
        return jsonify({"error": "forbidden"}), 403
    title = (request.get_json(force=True).get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    existing = db.select("wt_subtasks", eq={"task_id": tid})
    row = db.insert("wt_subtasks", {"task_id": tid, "title": title[:300],
                                    "position": len(existing)})
    return jsonify(row), 201


@app.patch("/api/subtasks/<sid>")
def api_update_subtask(sid):
    rows = db.select("wt_subtasks", eq={"id": sid})
    if not rows:
        return jsonify({"error": "not found"}), 404
    t = get_task_or_404(rows[0]["task_id"])
    if not t or not can_edit(t):
        return jsonify({"error": "forbidden"}), 403
    b = request.get_json(force=True)
    patch = {k: b[k] for k in ("title", "done", "position") if k in b}
    out = db.update("wt_subtasks", {"id": sid}, patch)
    return jsonify(out[0] if out else {})


@app.delete("/api/subtasks/<sid>")
def api_delete_subtask(sid):
    rows = db.select("wt_subtasks", eq={"id": sid})
    if rows:
        t = get_task_or_404(rows[0]["task_id"])
        if not t or not can_edit(t):
            return jsonify({"error": "forbidden"}), 403
        db.delete("wt_subtasks", {"id": sid})
    return jsonify({"ok": True})


@app.post("/api/tasks/<tid>/comments")
def api_add_comment(tid):
    t = get_task_or_404(tid)
    if not t:
        return jsonify({"error": "not found"}), 404
    if not task_visible(t, g.user["email"], g.perms["is_admin"], my_collab_ids(g.user["email"])):
        return jsonify({"error": "forbidden"}), 403
    body = (request.get_json(force=True).get("body") or "").strip()
    if not body:
        return jsonify({"error": "empty comment"}), 400
    row = db.insert("wt_comments", {"task_id": tid, "email": g.user["email"], "body": body[:4000]})
    return jsonify(row), 201


# ---------------- board APIs (Trello-style) ----------------

def ensure_board(email):
    lists = db.select("wt_lists", eq={"email": email})
    if not lists:
        lists = [db.insert("wt_lists", {"email": email, "name": name, "position": i})
                 for i, name in enumerate(DEFAULT_LISTS)]
    return sorted(lists, key=lambda l: l.get("position", 0))


@app.get("/api/board")
def api_board():
    email = request.args.get("user", g.user["email"]).lower()
    if email != g.user["email"] and not g.perms["is_admin"]:
        return jsonify({"error": "forbidden"}), 403
    lists = ensure_board(email)
    collab_ids = my_collab_ids(email)
    tasks = [t for t in db.select("wt_tasks", limit=1000)
             if t.get("assignee") == email or t["id"] in collab_ids]
    placements = {p["task_id"]: p for p in db.select("wt_placements", eq={"email": email})}
    first = lists[0]["id"]
    next_pos = max([p.get("position", 0) for p in placements.values()
                    if p.get("list_id") == first] or [-1]) + 1
    known_lists = {l["id"] for l in lists}
    for t in tasks:  # auto-place newly visible tasks at the end of the first list
        p = placements.get(t["id"])
        if not p or p.get("list_id") not in known_lists:
            if p:
                db.delete("wt_placements", {"task_id": t["id"], "email": email})
            placements[t["id"]] = db.insert("wt_placements", {
                "task_id": t["id"], "email": email, "list_id": first, "position": next_pos})
            next_pos += 1
    enrich(tasks)
    for t in tasks:
        p = placements[t["id"]]
        t["list_id"], t["position"] = p["list_id"], p.get("position", 0)
    return jsonify({"user": email, "lists": lists, "tasks": tasks})


@app.post("/api/lists")
def api_create_list():
    name = (request.get_json(force=True).get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    existing = db.select("wt_lists", eq={"email": g.user["email"]})
    row = db.insert("wt_lists", {"email": g.user["email"], "name": name[:80],
                                 "position": len(existing)})
    return jsonify(row), 201


@app.patch("/api/lists/<lid>")
def api_update_list(lid):
    rows = db.select("wt_lists", eq={"id": lid, "email": g.user["email"]})
    if not rows:
        return jsonify({"error": "not found"}), 404
    b = request.get_json(force=True)
    patch = {k: b[k] for k in ("name", "position") if k in b}
    out = db.update("wt_lists", {"id": lid}, patch)
    return jsonify(out[0] if out else {})


@app.delete("/api/lists/<lid>")
def api_delete_list(lid):
    mine = ensure_board(g.user["email"])
    if len(mine) <= 1:
        return jsonify({"error": "a board needs at least one list"}), 400
    if not any(l["id"] == lid for l in mine):
        return jsonify({"error": "not found"}), 404
    fallback = next(l["id"] for l in mine if l["id"] != lid)
    db.update("wt_placements", {"list_id": lid, "email": g.user["email"]},
              {"list_id": fallback})
    db.delete("wt_lists", {"id": lid})
    return jsonify({"ok": True})


@app.post("/api/board/move")
def api_move_card():
    b = request.get_json(force=True)
    tid, lid, index = b.get("task_id"), b.get("list_id"), int(b.get("index", 0))
    email = g.user["email"]
    if not db.select("wt_lists", eq={"id": lid, "email": email}):
        return jsonify({"error": "unknown list"}), 400
    siblings = [p for p in db.select("wt_placements", eq={"email": email, "list_id": lid})
                if p["task_id"] != tid]
    siblings.sort(key=lambda p: p.get("position", 0))
    order = [p["task_id"] for p in siblings]
    order.insert(max(0, min(index, len(order))), tid)
    db.update("wt_placements", {"task_id": tid, "email": email}, {"list_id": lid})
    for i, task_id in enumerate(order):
        db.update("wt_placements", {"task_id": task_id, "email": email}, {"position": i})
    return jsonify({"ok": True})


# ---------------- admin APIs ----------------

@app.get("/api/admin/users")
@admin_only
def api_admin_users():
    users = db.select("wt_users", order="created_at.asc")
    for u in users:
        u.pop("pw_hash", None)
    return jsonify({"users": users, "roles": list(roles_mod.all_roles().values())})


@app.post("/api/admin/users")
@admin_only
def api_admin_create_user():
    b = request.get_json(force=True)
    email = (b.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return jsonify({"error": "valid email required"}), 400
    if get_user(email):
        return jsonify({"error": "user already exists"}), 400
    role = (b.get("role") or "viewer").lower()
    if not roles_mod.get(role):
        return jsonify({"error": "unknown role"}), 400
    pw = b.get("password") or pysecrets.token_urlsafe(9)
    db.insert("wt_users", {"email": email, "name": b.get("name") or "", "role": role,
                           "pw_hash": generate_password_hash(pw), "must_change": True})
    return jsonify({"email": email, "temp_password": pw}), 201


@app.patch("/api/admin/users/<email>")
@admin_only
def api_admin_update_user(email):
    email = email.lower()
    if not get_user(email):
        return jsonify({"error": "not found"}), 404
    b = request.get_json(force=True)
    patch = {}
    if "name" in b:
        patch["name"] = b["name"]
    if "role" in b:
        if not roles_mod.get(b["role"]):
            return jsonify({"error": "unknown role"}), 400
        patch["role"] = b["role"]
    if "active" in b:
        if email == g.user["email"] and not b["active"]:
            return jsonify({"error": "you cannot deactivate yourself"}), 400
        patch["active"] = bool(b["active"])
    out = {"ok": True}
    if b.get("reset_password"):
        pw = pysecrets.token_urlsafe(9)
        patch["pw_hash"] = generate_password_hash(pw)
        patch["must_change"] = True
        out["temp_password"] = pw
    if patch:
        db.update("wt_users", {"email": email}, patch)
    return jsonify(out)


@app.post("/api/admin/roles")
@admin_only
def api_admin_create_role():
    b = request.get_json(force=True)
    slug = (b.get("role") or "").strip().lower().replace(" ", "_")
    if not slug:
        return jsonify({"error": "role slug required"}), 400
    if roles_mod.get(slug):
        return jsonify({"error": "role already exists"}), 400
    row = db.insert("wt_roles", {"role": slug, "label": b.get("label") or slug.title(),
                                 "description": b.get("description") or "",
                                 "skills": b.get("skills") or [],
                                 "is_admin": bool(b.get("is_admin"))})
    return jsonify(row), 201


@app.patch("/api/admin/roles/<slug>")
@admin_only
def api_admin_update_role(slug):
    if not roles_mod.get(slug):
        return jsonify({"error": "not found"}), 404
    b = request.get_json(force=True)
    patch = {k: b[k] for k in ("label", "description", "skills") if k in b}
    if "is_admin" in b and slug != "marketing_manager":
        patch["is_admin"] = bool(b["is_admin"])
    out = db.update("wt_roles", {"role": slug}, patch)
    return jsonify(out[0] if out else {})


@app.delete("/api/admin/roles/<slug>")
@admin_only
def api_admin_delete_role(slug):
    r = roles_mod.get(slug)
    if not r:
        return jsonify({"error": "not found"}), 404
    if r.get("builtin"):
        return jsonify({"error": "built-in roles cannot be deleted"}), 400
    if db.select("wt_users", eq={"role": slug}, limit=1):
        return jsonify({"error": "role is still assigned to users"}), 400
    db.delete("wt_roles", {"role": slug})
    return jsonify({"ok": True})


@app.post("/api/admin/analyze")
@admin_only
def api_admin_analyze():
    b = request.get_json(force=True)
    text = (b.get("text") or "").strip()
    if not text:
        return jsonify({"error": "paste some meeting notes or a transcript first"}), 400
    try:
        result = ai.analyze(text, source="manual",
                            source_ref=f"paste-{pysecrets.token_hex(6)}",
                            meeting_title=b.get("meeting_title") or "Pasted notes",
                            meeting_date=b.get("meeting_date") or dt.date.today().isoformat())
        return jsonify(result)
    except Exception as e:  # surface config problems (missing API key etc.) to the admin
        log.exception("analyze failed")
        return jsonify({"error": str(e)}), 500


@app.post("/api/admin/sync/<source>")
@admin_only
def api_admin_sync(source):
    try:
        if source == "fireflies":
            return jsonify(integrations.fireflies_sync())
        if source == "teams":
            return jsonify(integrations.teams_sync())
    except Exception as e:
        log.exception("sync failed")
        return jsonify({"error": str(e)}), 500
    return jsonify({"error": "unknown source"}), 404


@app.get("/api/admin/meetings")
@admin_only
def api_admin_meetings():
    rows = db.select("wt_meetings", order="processed_at.desc", limit=50)
    return jsonify([r for r in rows if not r["id"].endswith(":cursor")])


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5001)))
