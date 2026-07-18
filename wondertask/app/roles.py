"""Team roles with skills breakdowns — the ground truth the AI allocator matches against.

Seeded into wt_roles on first boot; the marketing manager can edit skills / add roles in
Admin → Roles. A role only ever receives AI-allocated tasks whose required skills overlap its
skills list — the Content & Social Manager never gets creative/design tasks, the Designer never
gets content tasks, the CRM Manager gets HubSpot/campaign/workflow tasks, and anything the AI
cannot confidently place lands in the marketing manager's Needs-Allocation pool instead.
"""
import db

SEED_ROLES = [
    {"role": "marketing_manager", "label": "Marketing Manager", "is_admin": True, "builtin": True,
     "description": "Owns the marketing plan, budget and team. Sees everything; allocates any task "
                    "the AI could not confidently match to a role.",
     "skills": ["marketing strategy", "campaign planning", "budget", "approvals", "reporting",
                "team management", "task allocation", "stakeholder communication"]},
    {"role": "content_social", "label": "Content & Social Manager", "builtin": True,
     "description": "Writes and publishes content; runs the social channels. Does NOT do "
                    "creative/design work.",
     "skills": ["content writing", "copywriting", "blog articles", "social media posts",
                "captions", "community management", "content calendar", "scheduling posts",
                "seo", "newsletters"]},
    {"role": "designer", "label": "Designer", "builtin": True,
     "description": "Creative and visual work only. Does NOT write content or run campaigns.",
     "skills": ["graphic design", "creative concepts", "visuals", "branding", "artwork",
                "banners", "video editing", "photo editing", "canva", "illustrations",
                "print design", "packaging design"]},
    {"role": "crm_manager", "label": "CRM Manager", "builtin": True,
     "description": "Owns HubSpot and the customer database. Marketing automation, not content.",
     "skills": ["crm", "hubspot", "email campaigns", "marketing automation", "workflows",
                "lead nurturing", "segmentation", "landing pages", "forms", "lists",
                "campaign reporting", "data hygiene"]},
    {"role": "viewer", "label": "Viewer", "builtin": True,
     "description": "Read-only teammate with no specialty — receives only manually assigned tasks.",
     "skills": []},
]


def ensure_seed():
    """Insert the built-in roles if the table is empty (idempotent, safe on every boot)."""
    if not db.select("wt_roles", limit=1):
        for r in SEED_ROLES:
            db.upsert("wt_roles", dict(r))


def all_roles():
    rows = db.select("wt_roles", order="created_at.asc")
    return {r["role"]: r for r in rows}


def get(role):
    rows = db.select("wt_roles", eq={"role": (role or "").lower()})
    return rows[0] if rows else None


def is_admin(role):
    r = get(role)
    return bool(r and r.get("is_admin"))
