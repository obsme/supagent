"""Three roles only: Admin, Editor, Viewer (0.9.6.6, the user's request of 6 October 2026).

supagent 0.9.6 made the roles AI Admin, AI Editor and AI Viewer next to Superset's own Admin, Alpha and Gamma. With
`superset supagent roles --apply` they are one set: AI Admin's users get Admin, AI Editor's Editor, AI Viewer's (and
the earlier AI Agent's) Viewer; Alpha is renamed Editor and Gamma Viewer (the same roles: their users, their row
level security filters and dashboards keep them); the AI roles go. From then on Superset's own role sync (`superset
init`, `superset supagent init`) makes Editor and Viewer where it made Alpha and Gamma, always as supagent made its
roles: Editor = Alpha and sql_lab without deleting, Viewer = Gamma without anything that changes something (the data:
none, or every database with roles.viewer_data "all"), each with supagent's own permissions; Admin = everything.
Nothing makes Alpha and Gamma again while roles.simple is on. A copy of every user's roles is kept before
(supagent_meta "roles_backup"): `--undo` gives Alpha, Gamma and the AI roles back, the users' roles as they were.

`superset supagent roles` (no option) says what would change, what in the configuration names the roles that go
(AUTH_USER_REGISTRATION_ROLE, AUTH_ROLES_MAPPING, PUBLIC_ROLE_LIKE...) and what uses them; nothing is changed.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from superset import db

log = logging.getLogger(__name__)

SETTING = "roles.simple"
RENAMED = {"Alpha": "Editor", "Gamma": "Viewer"}
KIND = {"Editor": "editor", "Viewer": "viewer"}
MERGED = {"AI Admin": "Admin", "AI Editor": "Editor", "AI Viewer": "Viewer", "AI Agent": "Viewer"}
BACKUP_KEY = "roles_backup"
CONFIG_KEYS = ("AUTH_USER_REGISTRATION_ROLE", "AUTH_ROLES_MAPPING", "PUBLIC_ROLE_LIKE", "GUEST_ROLE_NAME",
               "AUTH_ROLE_PUBLIC", "AUTH_ROLE_ADMIN")


class RolesError(Exception):
    pass


def simple() -> bool:
    """roles.simple: the roles are Admin, Editor and Viewer. Read on a connection of its own: it is asked during
    Superset's role sync, whose changes the session holds (a first `superset init`, before supagent's tables exist,
    must not lose them to a rollback)."""
    import sqlalchemy as sa

    try:
        with db.engine.connect() as conn:
            value = conn.execute(sa.text("SELECT value FROM supagent_setting WHERE key = :k"), {"k": SETTING}).scalar()
    except Exception:  # pylint: disable=broad-except   (no settings table yet: off)
        return False
    if isinstance(value, str):
        import json

        try:
            value = json.loads(value)
        except ValueError:
            return False
    return bool(value)


def _viewer_data_all() -> bool:
    import sqlalchemy as sa

    try:
        with db.engine.connect() as conn:
            value = conn.execute(sa.text("SELECT value FROM supagent_setting WHERE key = :k"),
                                 {"k": "roles.viewer_data"}).scalar()
    except Exception:  # pylint: disable=broad-except   (no settings table yet)
        return False
    return "all" in str(value or "")


def install(sm: Any) -> None:
    """Superset's role sync makes Editor and Viewer where it makes Alpha and Gamma, while roles.simple is on."""
    if getattr(sm, "_supagent_roles", False):
        return
    original = sm.set_role

    def set_role(role_name: str, pvm_check: Any, pvms: Any, *args: Any, **kwargs: Any) -> Any:
        target = RENAMED.get(role_name)
        if target is None or not simple():
            return original(role_name, pvm_check, pvms, *args, **kwargs)
        out = original(target, check_of(sm, target, pvm_check), pvms, *args, **kwargs)
        _complete(sm, target)
        return out

    sm.set_role = set_role
    sm._supagent_roles = True


def check_of(sm: Any, target: str, pvm_check: Any) -> Any:
    """Which of Superset's permissions the role has: Editor = Alpha's and sql_lab's without deleting (Superset's can_write
    on a chart or a dashboard also deletes the ones a user owns: that one stays); Viewer = Gamma's without any that
    changes something (favorites are a user's own)."""
    from supagent.cli import FAVORITE, WRITE_LIKE

    sql_lab = getattr(sm, "_is_sql_lab_pvm", None)
    if target == "Editor":
        return lambda p: (pvm_check(p) or bool(sql_lab and sql_lab(p))) and "delete" not in p.permission.name.lower()
    return lambda p: pvm_check(p) and (not WRITE_LIKE.search(p.permission.name) or bool(FAVORITE.search(p.permission.name)))


def _complete(sm: Any, target: str) -> None:
    """supagent's own permissions of the role (and every database for Viewer with roles.viewer_data "all")."""
    from supagent.cli import DATA_ALL, _agent_permissions

    role = sm.find_role(target)
    if role is None:
        return
    pvms = [sm.find_permission_view_menu(p, v) or sm.add_permission_view_menu(p, v) for p, v in _agent_permissions(KIND[target])]
    if target == "Viewer" and _viewer_data_all():
        pvms += [p for p in (sm.find_permission_view_menu(n, n) for n in DATA_ALL) if p is not None]
    for pvm in pvms:
        if pvm is not None and pvm not in role.permissions:
            role.permissions.append(pvm)


def _named(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return {n for v in value.values() for n in _named(v)}
    if isinstance(value, (list, tuple, set)):
        return {n for v in value for n in _named(v)}
    return set()


def plan() -> dict[str, Any]:
    """What --apply would change, and what stops it (nothing is changed)."""
    from flask import current_app
    from superset.extensions import security_manager as sm

    roles = {r.name: r for r in db.session.query(sm.role_model)}
    users = {name: sorted(u.username for u in r.user) for name, r in roles.items()}
    going = [n for n in list(RENAMED) + list(MERGED) if n in roles]
    config = {}
    for key in CONFIG_KEYS:
        named = _named(current_app.config.get(key)) & set(going)
        if named:
            config[key] = sorted(named)
    used: dict[str, list[str]] = {}
    for name in MERGED:                           # (the renamed roles keep their row level security and dashboards)
        if name not in roles:
            continue
        rid = roles[name].id
        try:
            from superset.connectors.sqla.models import RowLevelSecurityFilter
            from superset.models.dashboard import Dashboard

            rls = [f.name for f in db.session.query(RowLevelSecurityFilter) if any(r.id == rid for r in f.roles)]
            dash = [d.dashboard_title for d in db.session.query(Dashboard) if any(r.id == rid for r in d.roles)]
        except Exception:  # pylint: disable=broad-except   (another Superset: not checked)
            db.session.rollback()
            rls, dash = [], []
        if rls or dash:
            used[name] = [f"row level security {x!r}" for x in rls] + [f"dashboard {x!r}" for x in dash]
    groups: dict[str, list[str]] = {}
    group_model = getattr(sm, "group_model", None)
    if group_model is not None:
        for grp in db.session.query(group_model):
            names = sorted(r.name for r in getattr(grp, "roles", []) if r.name in MERGED)
            if names:
                groups[grp.name] = names
    clash = [new for old, new in RENAMED.items() if old in roles and new in roles]
    return {"simple": simple(), "roles": {n: len(u) for n, u in sorted(users.items())},
            "rename": [[o, n] for o, n in RENAMED.items() if o in roles],
            "merge": {n: {"to": MERGED[n], "users": users.get(n, [])} for n in MERGED if n in roles},
            "groups": groups, "config": config, "used": used, "clash": clash}


def text(p: dict[str, Any]) -> str:
    """The plan in lines (the command line)."""
    out = ["Roles now: " + ", ".join(f"{n} ({c} user{'s' if c != 1 else ''})" for n, c in p["roles"].items())]
    if p["simple"]:
        out.append("The roles are Admin, Editor and Viewer already (roles.simple): --undo goes back.")
    for old, new in p["rename"]:
        out.append(f"  {old} is renamed {new} (its users, row level security filters and dashboards keep it)")
    for name, m in p["merge"].items():
        who = ", ".join(m["users"][:8]) + (f" and {len(m['users']) - 8} more" if len(m["users"]) > 8 else "")
        out.append(f"  {name} goes; its users get {m['to']}" + (f": {who}" if who else " (no user)"))
    for grp, names in p["groups"].items():
        out.append(f"  group {grp!r}: " + ", ".join(f"{n} -> {MERGED[n]}" for n in names))
    for key, names in p["config"].items():
        out.append(f"  STOP: superset_config.py {key} names {', '.join(names)}: write "
                   + ", ".join(f"{n} -> {RENAMED.get(n) or MERGED.get(n)}" for n in names) + " there first")
    for name, what in p["used"].items():
        out.append(f"  STOP: {name} is used by " + ", ".join(what[:6]) + (" and more" if len(what) > 6 else "")
                   + f": give them {MERGED[name]} first (or --force: they lose {name})")
    for new in p["clash"]:
        out.append(f"  note: a role {new} exists already: the users of the one renamed join it")
    return "\n".join(out)


def _backup(sm: Any) -> dict[str, Any]:
    from supagent.models import Meta

    users = {u.username: sorted(r.name for r in u.roles) for u in db.session.query(sm.user_model)}
    group_model = getattr(sm, "group_model", None)
    groups = ({g.name: sorted(r.name for r in getattr(g, "roles", [])) for g in db.session.query(group_model)}
              if group_model is not None else {})
    data = {"at": dt.datetime.utcnow().isoformat(timespec="seconds"), "users": users, "groups": groups}
    row = db.session.get(Meta, BACKUP_KEY)
    if row is None:
        db.session.add(Meta(key=BACKUP_KEY, value=json.dumps(data)))
    else:
        row.value = json.dumps(data)
    return data


def apply(by: str, force: bool = False) -> dict[str, Any]:
    """Admin, Editor and Viewer only (see the module). Raises RolesError when something stops it."""
    from superset.extensions import security_manager as sm

    from supagent import settings

    p = plan()
    if p["simple"]:
        raise RolesError("the roles are Admin, Editor and Viewer already")
    if p["config"] or (p["used"] and not force):
        raise RolesError(text(p))
    _backup(sm)
    for old, new in RENAMED.items():
        r_old, r_new = sm.find_role(old), sm.find_role(new)
        if r_old is None:
            continue
        if r_new is None:
            r_old.name = new                              # the same role: its id, users, filters, dashboards
        else:
            for u in list(r_old.user):
                if r_new not in u.roles:
                    u.roles.append(r_new)
            db.session.delete(r_old)
    db.session.flush()
    group_model = getattr(sm, "group_model", None)
    for name, target in MERGED.items():
        r = sm.find_role(name)
        if r is None:
            continue
        t = sm.find_role(target) or sm.add_role(target)
        for u in list(r.user):
            have = {x.name for x in u.roles}
            if name == "AI Agent" and have & {"Admin", "Editor", "Viewer"}:
                continue                                  # (the earlier role: chat for whom has no role of the three)
            if t not in u.roles:
                u.roles.append(t)
        if group_model is not None:
            for grp in db.session.query(group_model):
                if r in getattr(grp, "roles", []) and t not in grp.roles:
                    grp.roles.append(t)
        db.session.delete(r)
    settings.set_value(SETTING, True, by=by)
    db.session.commit()
    install(sm)
    sm.sync_role_definitions()
    db.session.commit()
    return plan()


def undo(by: str) -> dict[str, Any]:
    """Alpha, Gamma and the AI roles back, every user's and group's roles as they were before --apply (a user made
    since keeps Editor as Alpha with AI Editor, Viewer as Gamma with AI Viewer)."""
    from superset.extensions import security_manager as sm

    from supagent import settings
    from supagent.cli import ROLE, _role_permissions, ensure_roles
    from supagent.models import Meta

    row = db.session.get(Meta, BACKUP_KEY)
    try:
        backup = json.loads(row.value) if row is not None and row.value else None
    except ValueError:
        backup = None
    if not simple() or not backup:
        raise RolesError("nothing to undo: the roles were not made Admin, Editor and Viewer by this command")
    settings.set_value(SETTING, False, by=by)
    for old, new in RENAMED.items():
        r_new, r_old = sm.find_role(new), sm.find_role(old)
        if r_new is not None and r_old is None:
            r_new.name = old
    db.session.commit()
    sm.sync_role_definitions()                            # Alpha and Gamma as Superset makes them
    ensure_roles(_viewer_data_all())                      # AI Admin, AI Editor, AI Viewer
    agent = sm.find_role(ROLE) or sm.add_role(ROLE)
    for perm, view in _role_permissions():
        pvm = sm.find_permission_view_menu(perm, view) or sm.add_permission_view_menu(perm, view)
        if pvm not in agent.permissions:
            agent.permissions.append(pvm)
    since = {"Alpha": "AI Editor", "Gamma": "AI Viewer"}
    for u in db.session.query(sm.user_model):
        names = backup["users"].get(u.username)
        if names is None:                                 # made since: its supagent role too
            for r in list(u.roles):
                extra = sm.find_role(since[r.name]) if r.name in since else None
                if extra is not None and extra not in u.roles:
                    u.roles.append(extra)
            continue
        u.roles = [r for r in (sm.find_role(n) for n in names) if r is not None]
    group_model = getattr(sm, "group_model", None)
    if group_model is not None:
        for grp in db.session.query(group_model):
            names = (backup.get("groups") or {}).get(grp.name)
            if names is not None:
                grp.roles = [r for r in (sm.find_role(n) for n in names) if r is not None]
    db.session.commit()
    return plan()
