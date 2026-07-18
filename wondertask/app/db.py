"""Data layer — Supabase REST (service key) in production, in-memory store in local dev.

Mirrors the wunderdog-dashboard convention: talk to Supabase's PostgREST API directly with the
service key (bypasses RLS; the anon key can never read these tables). When SUPABASE_URL /
SUPABASE_SERVICE_KEY are unset the same interface runs against a process-local store seeded with
demo data, so the app can be developed and smoke-tested without any credentials.
"""
import datetime as dt
import json
import os
import threading
import urllib.parse
import urllib.request
import uuid

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
HAS_DB = bool(SUPABASE_URL and SUPABASE_KEY)


# ---------------- Supabase REST backend ----------------

def _headers(extra=None):
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
         "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _request(method, path, body=None, prefer=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body is not None else None
    extra = {"Prefer": prefer} if prefer else None
    req = urllib.request.Request(url, data=data, headers=_headers(extra), method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
    return json.loads(raw) if raw else []


def _qs(eq=None, in_=None, order=None, limit=None, extra=None):
    parts = []
    for col, val in (eq or {}).items():
        if val is None:
            parts.append(f"{col}=is.null")
        else:
            parts.append(f"{col}=eq.{urllib.parse.quote(str(val))}")
    for col, vals in (in_ or {}).items():
        joined = ",".join(urllib.parse.quote(f'"{v}"') for v in vals)
        parts.append(f"{col}=in.({joined})")
    if order:
        parts.append(f"order={order}")
    if limit:
        parts.append(f"limit={limit}")
    if extra:
        parts.append(extra)
    return "&".join(parts)


# ---------------- in-memory dev backend ----------------

_MEM = {}
_MEM_LOCK = threading.Lock()
_PK = {"wt_users": "email", "wt_roles": "role", "wt_meetings": "id"}
_DEFAULTS = {
    "wt_tasks": {"status": "todo", "acceptance": "accepted", "source": "manual"},
    "wt_subtasks": {"done": False, "position": 0},
    "wt_lists": {"position": 0},
    "wt_placements": {"position": 0},
    "wt_users": {"active": True, "must_change": True, "role": "viewer"},
    "wt_roles": {"skills": [], "is_admin": False, "builtin": False},
    "wt_meetings": {"tasks_created": 0, "tasks_matched": 0},
}


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _mem_insert(table, row):
    row = dict(row)
    pk = _PK.get(table, "id")
    if pk == "id" and "id" not in row:
        row["id"] = str(uuid.uuid4())
    for k, v in _DEFAULTS.get(table, {}).items():
        row.setdefault(k, v)
    row.setdefault("created_at", _now())
    if table == "wt_tasks":
        row.setdefault("updated_at", _now())
    with _MEM_LOCK:
        _MEM.setdefault(table, []).append(row)
    return dict(row)


def _mem_match(row, eq, in_):
    for col, val in (eq or {}).items():
        if row.get(col) != val:
            return False
    for col, vals in (in_ or {}).items():
        if row.get(col) not in vals:
            return False
    return True


def _mem_select(table, eq=None, in_=None, order=None, limit=None):
    with _MEM_LOCK:
        rows = [dict(r) for r in _MEM.get(table, []) if _mem_match(r, eq, in_)]
    if order:
        col, _, direction = order.partition(".")
        rows.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=(direction == "desc"))
    return rows[:limit] if limit else rows


# ---------------- public interface ----------------

def select(table, eq=None, in_=None, order=None, limit=None):
    if HAS_DB:
        return _request("GET", f"{table}?{_qs(eq, in_, order, limit, 'select=*')}")
    return _mem_select(table, eq, in_, order, limit)


def insert(table, row):
    """Insert one row; returns it (with generated id/defaults)."""
    if HAS_DB:
        out = _request("POST", table, body=row, prefer="return=representation")
        return out[0] if isinstance(out, list) and out else row
    return _mem_insert(table, row)


def upsert(table, row):
    if HAS_DB:
        out = _request("POST", table, body=row,
                       prefer="resolution=merge-duplicates,return=representation")
        return out[0] if isinstance(out, list) and out else row
    pk = _PK.get(table, "id")
    with _MEM_LOCK:
        _MEM.setdefault(table, [])
        _MEM[table] = [r for r in _MEM[table] if r.get(pk) != row.get(pk)]
    return _mem_insert(table, row)


def update(table, eq, patch):
    if HAS_DB:
        return _request("PATCH", f"{table}?{_qs(eq)}", body=patch,
                        prefer="return=representation")
    out = []
    with _MEM_LOCK:
        for r in _MEM.get(table, []):
            if _mem_match(r, eq, None):
                r.update(patch)
                out.append(dict(r))
    return out


def delete(table, eq):
    if HAS_DB:
        _request("DELETE", f"{table}?{_qs(eq)}")
        return
    with _MEM_LOCK:
        _MEM[table] = [r for r in _MEM.get(table, []) if not _mem_match(r, eq, None)]
