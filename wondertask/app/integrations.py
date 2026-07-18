"""Fireflies + Microsoft Teams connectors, and Graph mail for reminders.

All network access is plain REST (urllib) with credentials from environment variables — the same
pattern (and the same Microsoft app registration variables) as wunderdog-dashboard:
  FIREFLIES_API_KEY                          — Fireflies GraphQL API key
  MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET — Graph app registration (client credentials)
  TEAMS_TEAM_ID / TEAMS_CHANNEL_ID           — the Teams channel to analyze
  MAIL_SENDER                                — mailbox reminders are sent from (optional)

Every connector degrades to a clear "not configured" message instead of crashing, so the app and
crons stay deploy-safe before credentials are added.
"""
import datetime as dt
import json
import os
import urllib.parse
import urllib.request

import ai
import db

FIREFLIES_URL = "https://api.fireflies.ai/graphql"


def _post_json(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


# ---------------- Fireflies ----------------

def fireflies_sync(limit=10):
    """Fetch recent Fireflies transcripts and run the AI allocator over any not yet processed."""
    key = os.environ.get("FIREFLIES_API_KEY", "")
    if not key:
        return {"error": "FIREFLIES_API_KEY is not set — add it to enable Fireflies sync."}
    query = """query Transcripts($limit: Int) {
      transcripts(limit: $limit) {
        id title date
        summary { overview action_items }
        sentences { speaker_name text }
      }
    }"""
    out = _post_json(FIREFLIES_URL, {"query": query, "variables": {"limit": limit}},
                     {"Authorization": f"Bearer {key}"})
    if out.get("errors"):
        return {"error": f"Fireflies API error: {out['errors']}"}
    results = []
    for t in (out.get("data") or {}).get("transcripts") or []:
        tid = t.get("id")
        if not tid or ai.already_processed("fireflies", tid):
            continue
        when = None
        if t.get("date"):
            try:  # Fireflies returns epoch milliseconds
                when = dt.datetime.fromtimestamp(float(t["date"]) / 1000,
                                                 dt.timezone.utc).date().isoformat()
            except (ValueError, TypeError):
                when = None
        summary = t.get("summary") or {}
        parts = []
        if summary.get("overview"):
            parts.append(f"MEETING OVERVIEW:\n{summary['overview']}")
        if summary.get("action_items"):
            items = summary["action_items"]
            parts.append("FIREFLIES ACTION ITEMS:\n" +
                         (items if isinstance(items, str) else "\n".join(map(str, items))))
        sentences = t.get("sentences") or []
        if sentences:
            transcript = "\n".join(f"{s.get('speaker_name') or '?'}: {s.get('text') or ''}"
                                   for s in sentences)
            parts.append(f"TRANSCRIPT:\n{transcript}")
        text = "\n\n".join(parts).strip()
        if not text:
            continue
        result = ai.analyze(text, source="fireflies", source_ref=tid,
                            meeting_title=t.get("title") or "Fireflies meeting",
                            meeting_date=when)
        result["meeting"] = t.get("title")
        results.append(result)
    return {"processed": len(results), "results": results}


# ---------------- Microsoft Teams ----------------

def _graph_token():
    tenant = os.environ.get("MS_TENANT_ID", "")
    client = os.environ.get("MS_CLIENT_ID", "")
    secret = os.environ.get("MS_CLIENT_SECRET", "")
    if not (tenant and client and secret):
        return None
    body = urllib.parse.urlencode({
        "client_id": client, "client_secret": secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("access_token")


def teams_sync():
    """Analyze new messages in the configured Teams channel (batch per run, cursor-tracked)."""
    team = os.environ.get("TEAMS_TEAM_ID", "")
    channel = os.environ.get("TEAMS_CHANNEL_ID", "")
    if not (team and channel):
        return {"error": "TEAMS_TEAM_ID / TEAMS_CHANNEL_ID are not set — add them to enable "
                         "Teams sync (plus MS_* Graph credentials with ChannelMessage.Read.All)."}
    token = _graph_token()
    if not token:
        return {"error": "MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET are not set."}
    url = (f"https://graph.microsoft.com/v1.0/teams/{team}/channels/{channel}"
           f"/messages?$top=50")
    out = _get_json(url, {"Authorization": f"Bearer {token}"})
    msgs = out.get("value") or []

    cursor_id = f"teams:{channel}:cursor"
    cursor_rows = db.select("wt_meetings", eq={"id": cursor_id})
    cursor = cursor_rows[0].get("title") if cursor_rows else None  # ISO datetime of last seen msg

    fresh = []
    newest = cursor
    for m in msgs:
        created = m.get("createdDateTime") or ""
        body = ((m.get("body") or {}).get("content") or "").strip()
        sender = (((m.get("from") or {}).get("user") or {}).get("displayName")) or "?"
        if not body or (cursor and created <= cursor):
            continue
        # crude HTML strip — Teams bodies are HTML
        import re
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            fresh.append(f"[{created}] {sender}: {text}")
        if not newest or created > newest:
            newest = created
    if not fresh:
        return {"processed": 0, "results": [], "note": "no new messages"}

    batch_ref = f"{channel}:{newest}"
    result = ai.analyze("\n".join(fresh), source="teams", source_ref=batch_ref,
                        meeting_title="Teams channel discussion",
                        meeting_date=dt.date.today().isoformat())
    db.upsert("wt_meetings", {"id": cursor_id, "source": "teams", "title": newest,
                              "meeting_date": dt.date.today().isoformat()})
    return {"processed": 1, "messages_analyzed": len(fresh), "results": [result]}


# ---------------- reminder mail (optional) ----------------

def send_mail(to, subject, html):
    sender = os.environ.get("MAIL_SENDER", "")
    token = _graph_token()
    if not (sender and token):
        return False
    body = {"message": {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html},
        "toRecipients": [{"emailAddress": {"address": to}}]},
        "saveToSentItems": "false"}
    req = urllib.request.Request(
        f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30):
        return True


def due_reminders():
    """Email each member their overdue / due-soon open tasks. No-op until mail is configured."""
    today = dt.date.today()
    soon = (today + dt.timedelta(days=2)).isoformat()
    tasks = [t for t in db.select("wt_tasks")
             if t.get("status") != "done" and t.get("assignee")
             and (t.get("due_date") or "9999") <= soon]
    by_user = {}
    for t in tasks:
        by_user.setdefault(t["assignee"], []).append(t)
    sent = 0
    for email, items in by_user.items():
        items.sort(key=lambda t: t.get("due_date") or "")
        rows = "".join(
            f"<li><b>{t['title']}</b> — due {t.get('due_date')}"
            f"{' <b style=color:#c0392b>(overdue)</b>' if (t.get('due_date') or '') < today.isoformat() else ''}</li>"
            for t in items)
        if send_mail(email, "WonderTask: tasks due soon",
                     f"<p>These tasks are overdue or due within 2 days:</p><ul>{rows}</ul>"
                     f"<p><a href='{os.environ.get('APP_URL', '')}'>Open WonderTask</a></p>"):
            sent += 1
    return {"users_notified": sent, "tasks_flagged": len(tasks)}
