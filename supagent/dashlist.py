"""(0.10.10) The dashboards and visualizations of the team's Grafana and OpenSearch Dashboards, listed in Documents and
sites, and which of them the agent reads (the team's request: deactivate them all, then activate those it needs,
with each one's last modified date to choose from).

* The list is what the last reading found (supagent_dash_item): the learning's Grafana and OpenSearch Dashboards
  steps record it as they read, and "List now" reads it alone (no LLM, in the background). Each dashboard with its
  folder (Grafana) or index patterns (OpenSearch Dashboards), its last modified date and by whom, its link; each panel
  (Grafana) or visualization (OpenSearch Dashboards) with its type and the dashboards that show it.
* What is not read: its pages leave the Context and the search at once (deleted: a deactivation never waits in To
  review), the AI explains it no more, the agent's tools neither list nor read it, its panels are not watched. The
  checks that keep Grafana safe (a draft's duplicate title, its folder) still see every dashboard. Alert rules are
  not in the list (they are all read).
* A Grafana panel is read when it and its dashboard are. An OpenSearch Dashboards visualization is one object that any
  number of dashboards show: it is read when it is (left out of the pages of the dashboards that show it otherwise);
  activating a dashboard activates the visualizations it shows, deactivating one deactivates those that no other
  dashboard read shows.
* A new item takes its source's default (grafana.read_new, osd.read_new): Deactivate all turns it off, Activate all
  on. A new panel of a Grafana dashboard is read, a new visualization of an OpenSearch Dashboards dashboard read too.
  An item never listed is read as before 0.10.10, unless that default is off.
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import json
import logging
import time
from typing import Any, Iterable

log = logging.getLogger(__name__)
SOURCES = ("grafana", "osd")
NAMES = {"grafana": "Grafana", "osd": "OpenSearch Dashboards"}
KIDS = {"grafana": ("panel",), "osd": ("visualization", "search")}
JOB = "dash_job:"                 # supagent_meta: the source's last job (list, pages): {what, running, started, ...}
STALE_JOB = 1800                  # seconds after which a job said running is taken as dead (its process stopped)
PAGE_SYNC_ONE_BY_ONE = 30         # pages deleted at most whose search pieces are removed one page at a time


class ListError(ValueError):
    pass


def _now() -> dt.datetime:
    return dt.datetime.utcnow().replace(microsecond=0)


def _source(source: str) -> str:
    if source not in SOURCES:
        raise ListError(f"unknown source {source!r}: grafana or osd")
    return source


def read_new(source: str) -> bool:
    from supagent import settings

    try:
        return bool(settings.get(f"{_source(source)}.read_new"))
    except Exception:  # pylint: disable=broad-except
        return True


def configured(source: str) -> bool:
    try:
        if source == "grafana":
            from supagent import grafana as G

            return G.configured()
        from supagent import osd

        return osd.configured()
    except Exception:  # pylint: disable=broad-except
        return False


def panel_ref(dashboard: Any, panel: dict[str, Any]) -> str:
    """A Grafana panel's key: its dashboard's UID and the panel's id (its title when it has none)."""
    pid = panel.get("id")
    return f"{dashboard}/{pid}" if pid not in (None, "") else f"{dashboard}/t:{str(panel.get('title') or '')[:80]}"


# --------------------------------------------------------------------------------------------------------------- #
# what the agent reads
# --------------------------------------------------------------------------------------------------------------- #
class Reading:
    """Which dashboards, panels and visualizations of a source the agent reads (one query; an item never listed: the
    source's default, a panel or a visualization of a dashboard read: read)."""

    def __init__(self, source: str) -> None:
        from superset import db

        self.source = _source(source)
        self.new = read_new(source)
        self.flags: dict[str, bool] = {}
        try:
            from supagent.models import DashItem

            for ref, active in db.session.query(DashItem.ref, DashItem.active).filter(DashItem.source == source):
                self.flags[str(ref)] = bool(active)
        except Exception:  # pylint: disable=broad-except   (no table yet, no application: everything read)
            try:
                db.session.rollback()
            except Exception:  # pylint: disable=broad-except
                pass
        self.everything = self.new and all(self.flags.values())

    def dashboard(self, ref: Any) -> bool:
        f = self.flags.get(str(ref))
        return self.new if f is None else f

    def panel(self, dashboard: Any, panel: dict[str, Any]) -> bool:
        """A Grafana panel: read when its dashboard is and it is not deactivated itself."""
        if not self.dashboard(dashboard):
            return False
        f = self.flags.get(panel_ref(dashboard, panel))
        return True if f is None else f

    def visualization(self, ref: Any, dashboards: Iterable[Any] = ()) -> bool:
        """An OpenSearch Dashboards visualization or saved search: its own flag; never listed: read when a dashboard
        read shows it, else the source's default."""
        f = self.flags.get(str(ref))
        if f is not None:
            return f
        return any(self.flags.get(str(d), self.new) for d in dashboards) or self.new


def reading(source: str) -> Reading:
    return Reading(source)


def without_unread(d: dict[str, Any], r: Reading | None = None) -> dict[str, Any]:
    """A condensed Grafana dashboard (grafana.condense) without the panels not read (their number said)."""
    r = r or Reading("grafana")
    if r.everything or not d.get("uid"):
        return d
    panels = d.get("panels") or []
    kept = [p for p in panels if r.panel(d["uid"], p)]
    if len(kept) == len(panels):
        return d
    return {**d, "panels": kept, "panels not read (deactivated in Documents and sites)": len(panels) - len(kept)}


# --------------------------------------------------------------------------------------------------------------- #
# the list, from a reading
# --------------------------------------------------------------------------------------------------------------- #
def _when(text: Any) -> dt.datetime | None:
    if isinstance(text, dt.datetime):
        return text.replace(tzinfo=None)
    t = str(text or "").strip()
    if not t or t.startswith("0001-"):
        return None
    try:
        when = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return when.replace(microsecond=0)


def record(source: str, items: list[dict[str, Any]], listed: bool, read: set[str] | None = None) -> dict[str, int]:
    """The list as a reading found it: `items` ({kind, ref, parent, title, folder, type, link, parents, children,
    updated_at, updated_by}) added or brought up to date; `listed`: every dashboard was listed (those not found are
    gone); `read`: the dashboards read whole (Grafana: their panels not found are gone; OpenSearch Dashboards: every
    object when `listed`). A new item takes its source's default (a panel or a visualization of a dashboard read:
    read). Counted."""
    from superset import db

    from supagent.models import DashItem

    _source(source)
    now = _now()
    new_default = read_new(source)
    have = {r.ref: r for r in db.session.query(DashItem).filter(DashItem.source == source)}
    out = {"new": 0, "updated": 0, "gone": 0, "back": 0}
    seen: set[str] = set()
    boards = {str(i["ref"]) for i in items if i.get("kind") == "dashboard"}
    on = {ref for ref in boards if (have[ref].active if ref in have else new_default)}
    for i in items:
        ref = str(i.get("ref") or "")
        if not ref or ref in seen:
            continue
        seen.add(ref)
        row = have.get(ref)
        if row is None:
            kind = i.get("kind") or "dashboard"
            if kind == "panel":
                active = True                            # a new panel: read as its dashboard is
            elif kind in ("visualization", "search"):
                active = new_default or bool(set(map(str, i.get("parents") or [])) & on)
            else:
                active = new_default
            row = DashItem(source=source, kind=kind, ref=ref[:255], active=active)
            db.session.add(row)
            have[ref] = row
            out["new"] += 1
        else:
            out["updated"] += 1
            if row.gone_at is not None:
                row.gone_at = None
                out["back"] += 1
        row.kind = i.get("kind") or row.kind              # what the reading said (a dashboard listed by the search
        for key, cut in (("parent", 190), ("title", 255), ("folder", 255), ("type", 64), ("link", 1000),   # only:
                         ("updated_by", 255)):                                  # its panels and date unknown)
            if key in i:
                setattr(row, key, str(i.get(key) or "")[:cut] or None)
        if "parents" in i:
            row.parents = [str(p) for p in i.get("parents") or []] or None
        if "children" in i:
            row.children = i.get("children")
        if "updated_at" in i:
            row.updated_at = _when(i.get("updated_at"))
        row.seen_at = now
    for ref, row in have.items():
        if ref in seen or row.gone_at is not None or row.kind == "panel":
            continue
        if listed:                                       # a dashboard (or an OpenSearch Dashboards object) gone
            row.gone_at = now
            out["gone"] += 1
    gone_boards = {ref for ref, row in have.items() if row.kind == "dashboard" and row.gone_at is not None}
    for ref, row in have.items():                       # a Grafana panel: gone with its dashboard, or from it
        if row.kind != "panel" or ref in seen or row.gone_at is not None:
            continue
        if row.parent in gone_boards or row.parent in (read or set()):
            row.gone_at = now
            out["gone"] += 1
    db.session.commit()
    return out


# --------------------------------------------------------------------------------------------------------------- #
# the list, as the page shows it
# --------------------------------------------------------------------------------------------------------------- #
def _row(r: Any, read_as: bool | None = None) -> dict[str, Any]:
    return {k: v for k, v in {
        "id": r.id, "kind": r.kind, "ref": r.ref, "parent": r.parent, "title": r.title, "folder": r.folder,
        "type": r.type, "link": r.link, "parents": r.parents, "children": r.children,
        "updated_at": r.updated_at.isoformat() + "Z" if r.updated_at else None, "updated_by": r.updated_by,
        "active": bool(r.active), "read": read_as, "set_by": r.set_by,
        "set_at": r.set_at.isoformat() + "Z" if r.set_at else None,
        "gone": r.gone_at is not None}.items() if v is not None}


def _matches(r: Any, words: list[str]) -> bool:
    text = " ".join(str(x or "") for x in (r.title, r.folder, r.type, r.ref)).lower()
    return all(w in text for w in words)


def _effective(source: str, rows: list[Any]) -> dict[int, bool]:
    """Whether each row is read now (a panel of a dashboard not read is not)."""
    by_ref = {r.ref: r for r in rows}
    out: dict[int, bool] = {}
    for r in rows:
        if r.gone_at is not None:
            out[r.id] = False
        elif source == "grafana" and r.kind == "panel":
            parent = by_ref.get(r.parent or "")
            out[r.id] = bool(r.active) and (parent is None or bool(parent.active))
        else:
            out[r.id] = bool(r.active)
    return out


def summary(source: str) -> dict[str, Any]:
    """A source's line in the page: is it set up, the counts (read / all), when it was listed, its job."""
    from superset import db

    from supagent.models import DashItem

    rows = db.session.query(DashItem).filter(DashItem.source == _source(source)).all()
    reads = _effective(source, rows)
    live = [r for r in rows if r.gone_at is None]
    boards = [r for r in live if r.kind == "dashboard"]
    kids = [r for r in live if r.kind in KIDS[source]]
    seen = [r.seen_at for r in rows if r.seen_at]
    url = ""
    try:
        from supagent import settings

        url = str(settings.get("grafana.url" if source == "grafana" else "osd.url") or "")
    except Exception:  # pylint: disable=broad-except
        pass
    return {"source": source, "name": NAMES[source], "configured": configured(source), "url": url,
            "read_new": read_new(source), "listed_at": max(seen).isoformat() + "Z" if seen else None,
            "dashboards": len(boards), "dashboards_read": sum(1 for r in boards if reads.get(r.id)),
            "kids": len(kids), "kids_read": sum(1 for r in kids if reads.get(r.id)),
            "kid": "panels" if source == "grafana" else "visualizations",
            "gone": len(rows) - len(live), "job": job(source)}


UNREAD_SAID = ("switched off for the agent in Documents and sites: they exist and are never read. A dashboard asked "
               "that is not in this list may be one of them: read it by its title (that says whether it is switched "
               "off) before saying it does not exist; never describe one (an admin can switch it on)")


def unread_named(source: str, query: str = "", limit: int = 10) -> dict[str, Any] | None:
    """(0.10.10, oq1 O5: "there is no dashboard titled ..." of one switched off) For a source's list tools: how many
    of its dashboards the agent does not read, and those whose title (or folder) has every word of `query`, by their
    title only. None when every dashboard listed is read."""
    import re

    from superset import db

    from supagent.models import DashItem

    try:
        rows = db.session.query(DashItem).filter(DashItem.source == _source(source), DashItem.kind == "dashboard",
                                                 DashItem.gone_at.is_(None)).all()
    except Exception:  # pylint: disable=broad-except   (no table yet: everything read)
        db.session.rollback()
        return None
    off = [r for r in rows if not r.active]
    if not off:
        return None
    words = [w for w in re.split(r"[\s,;:'\"]+", str(query or "").lower()) if w]
    named = sorted(str(r.title or r.ref) for r in off
                   if words and all(w in f"{r.title or ''} {r.folder or ''} {r.ref}".lower() for w in words))
    out: dict[str, Any] = {"count": len(off), "what to say": UNREAD_SAID}
    if named:
        out["named by the question"] = named[:max(1, int(limit))]
    return out


SORTS = {"updated": lambda r: (r.updated_at or dt.datetime.min), "title": lambda r: str(r.title or "").lower(),
         "folder": lambda r: (str(r.folder or "").lower(), str(r.title or "").lower())}


def rows(source: str, q: str = "", kind: str = "dashboard", state: str = "", sort: str = "updated",
         offset: int = 0, limit: int = 200) -> dict[str, Any]:
    """A page of the list: `kind` dashboard or the source's other kind (panel / visualization, a saved search
    with them), `state` read or unread (empty: both), the words of `q` in the title, folder or type; sorted by last
    modified (newest first), by title or by folder."""
    from superset import db

    from supagent.models import DashItem

    _source(source)
    every = db.session.query(DashItem).filter(DashItem.source == source).all()
    reads = _effective(source, every)
    kinds = ("dashboard",) if kind == "dashboard" else KIDS[source]
    words = [w for w in str(q or "").lower().split() if w]
    picked = [r for r in every if r.kind in kinds and r.gone_at is None and _matches(r, words)
              and (state != "read" or reads.get(r.id)) and (state != "unread" or not reads.get(r.id))]
    key = SORTS.get(sort) or SORTS["updated"]
    picked.sort(key=key, reverse=(sort not in ("title", "folder")))
    titles = {r.ref: r.title for r in every if r.kind == "dashboard"}
    page = picked[max(0, offset):max(0, offset) + max(1, min(limit, 1000))]
    out = []
    for r in page:
        x = _row(r, reads.get(r.id))
        if r.kind == "panel" and r.parent:
            x["dashboard"] = titles.get(r.parent)
        if r.parents:
            x["dashboards"] = [{"ref": p, "title": titles.get(p) or p} for p in r.parents]
        out.append(x)
    return {"source": source, "rows": out, "total": len(picked), "offset": offset}


def children(source: str, ref: str) -> list[dict[str, Any]]:
    """A dashboard's panels (Grafana) or visualizations (OpenSearch Dashboards: those that list it)."""
    from superset import db

    from supagent.models import DashItem

    every = db.session.query(DashItem).filter(DashItem.source == _source(source)).all()
    reads = _effective(source, every)
    if source == "grafana":
        mine = [r for r in every if r.kind == "panel" and r.parent == ref and r.gone_at is None]
    else:
        mine = [r for r in every if r.kind in KIDS["osd"] and ref in (r.parents or []) and r.gone_at is None]
    titles = {r.ref: r.title for r in every if r.kind == "dashboard"}
    out = []
    for r in mine:
        x = _row(r, reads.get(r.id))
        if r.parents:
            x["dashboards"] = [{"ref": p, "title": titles.get(p) or p} for p in r.parents]
        out.append(x)
    return out


# --------------------------------------------------------------------------------------------------------------- #
# activating, deactivating
# --------------------------------------------------------------------------------------------------------------- #
def _apply_flags(source: str, every: list[Any], targets: list[Any], active: bool, by: str) -> dict[str, Any]:
    """Set the flag of `targets` (rows) and cascade (OpenSearch Dashboards: a dashboard's visualizations). Returns
    the dashboards whose pages go now (off), those to write again (on, or whose panels changed)."""
    now = _now()
    changed: set[int] = set()
    off: set[str] = set()
    again: set[str] = set()
    boards = {r.ref: r for r in every if r.kind == "dashboard"}

    def flip(r: Any, value: bool) -> None:
        if bool(r.active) != value or r.set_by is None:
            if bool(r.active) != value:
                changed.add(r.id)
            r.active, r.set_by, r.set_at = value, by, now

    for r in targets:
        flip(r, active)
    cascaded = 0
    if source == "osd":
        kids = [r for r in every if r.kind in KIDS["osd"]]
        turned = [r for r in targets if r.kind == "dashboard"]
        for b in turned:
            for k in kids:
                if b.ref not in (k.parents or []) or k in targets:
                    continue
                if active and not k.active:
                    flip(k, True)
                    cascaded += 1
                elif not active and k.active and not any(
                        boards.get(p) is not None and boards[p].active for p in (k.parents or []) if p != b.ref):
                    flip(k, False)
                    cascaded += 1
    for r in every:
        if r.id not in changed:
            continue
        if r.kind == "dashboard":
            (again if r.active else off).add(r.ref)
        elif source == "grafana" and r.parent:
            again.add(r.parent)
        else:
            again.update(p for p in (r.parents or []) if boards.get(p) is not None and boards[p].active)
            again.add("")                               # OpenSearch Dashboards: the pages of the lone ones too
    again -= off
    return {"changed": len(changed), "cascaded": cascaded, "off": sorted(off), "again": sorted(again)}


def set_active(source: str, ids: list[int], active: bool, by: str) -> dict[str, Any]:
    """Items (by id) read or not, with their cascade; their pages follow (pages_follow)."""
    from superset import db

    from supagent.models import DashItem

    every = db.session.query(DashItem).filter(DashItem.source == _source(source)).all()
    want = {int(i) for i in ids}
    targets = [r for r in every if r.id in want]
    if len(targets) != len(want):
        raise ListError("no such item in the list: list it again")
    out = _apply_flags(source, every, targets, bool(active), by)
    db.session.commit()
    return out


def set_matching(source: str, active: bool, by: str, q: str = "", kind: str = "dashboard",
                 state: str = "") -> dict[str, Any]:
    """Every item the page shows for these filters (all its pages, not only the one on screen) read or not."""
    from superset import db

    from supagent.models import DashItem

    every = db.session.query(DashItem).filter(DashItem.source == _source(source)).all()
    reads = _effective(source, every)
    kinds = ("dashboard",) if kind == "dashboard" else KIDS[source]
    words = [w for w in str(q or "").lower().split() if w]
    targets = [r for r in every if r.kind in kinds and r.gone_at is None and _matches(r, words)
               and (state != "read" or reads.get(r.id)) and (state != "unread" or not reads.get(r.id))]
    out = _apply_flags(source, every, targets, bool(active), by)
    db.session.commit()
    out["items"] = len(targets)
    return out


def set_all(source: str, active: bool, by: str) -> dict[str, Any]:
    """Everything of the source read or not, and its new items too from now on (grafana.read_new, osd.read_new)."""
    from superset import db

    from supagent import settings
    from supagent.models import DashItem

    every = db.session.query(DashItem).filter(DashItem.source == _source(source)).all()
    targets = [r for r in every if r.kind == "dashboard" or source == "osd"]   # Grafana: the dashboards (each
    out = _apply_flags(source, every, targets, bool(active), by)               # panel keeps its own flag)
    settings.set_value(f"{source}.read_new", bool(active), by=by)
    db.session.commit()
    out["items"] = len(targets)
    out["read_new"] = bool(active)
    return out


def set_default(source: str, active: bool, by: str) -> dict[str, Any]:
    from supagent import settings

    settings.set_value(f"{_source(source)}.read_new", bool(active), by=by)
    return {"read_new": bool(active)}


# --------------------------------------------------------------------------------------------------------------- #
# the pages follow
# --------------------------------------------------------------------------------------------------------------- #
def page_slugs(source: str, refs: Iterable[str]) -> list[str]:
    if source == "grafana":
        from supagent.knowledge.grafana_pages import BOARD, _slug

        return [_slug(BOARD, r) for r in refs if r]
    from supagent.knowledge.osd_pages import BOARD as OSD_BOARD, _slug as osd_slug

    return [osd_slug(OSD_BOARD, r) for r in refs if r]


def unread_slugs() -> set[str]:
    """The slugs of the pages of every dashboard not read (both sources): such a page is deleted, never proposed for
    removal (a deactivation never waits in To review)."""
    from superset import db

    from supagent.models import DashItem

    out: set[str] = set()
    try:
        for source in SOURCES:
            refs = [r for (r,) in db.session.query(DashItem.ref).filter(DashItem.source == source,
                                                                        DashItem.kind == "dashboard",
                                                                        DashItem.active.is_(False))]
            out.update(page_slugs(source, refs))
    except Exception:  # pylint: disable=broad-except   (no table yet)
        db.session.rollback()
    return out


def drop_pages(source: str, refs: Iterable[str]) -> list[int]:
    """The Context pages of these dashboards deleted now (a page a person edited too: the dashboard is not read);
    their ids (their search pieces are removed by the caller)."""
    from superset import db

    from supagent.models import ContextPage

    slugs = page_slugs(source, refs)
    if not slugs:
        return []
    pages = db.session.query(ContextPage).filter(ContextPage.slug.in_(slugs)).all()
    ids = [p.id for p in pages]
    for p in pages:
        db.session.delete(p)
    db.session.commit()
    return ids


def pages_follow(source: str, done: dict[str, Any], dispatch: bool = True) -> dict[str, Any]:
    """After a change of the flags: the pages of the dashboards not read deleted now and their search pieces removed
    (in the background of this process); the pages of those read again or changed written again in the background
    (no LLM: an AI explanation already written for the same facts comes back, a new one is written at the next
    learning)."""
    ids = drop_pages(source, done.get("off") or [])
    _forget_pieces(ids)
    again = list(done.get("again") or [])
    if again and dispatch and _context_on(source):
        from supagent.tasks import dispatch_dash

        dispatch_dash(source, "pages", again)
    return {"pages_removed": len(ids), "pages_to_write": len([r for r in again if r])}


def _context_on(source: str) -> bool:
    try:
        if source == "grafana":
            from supagent.knowledge import grafana_pages as GP

            return GP.enabled()
        from supagent.knowledge import osd_pages as OP

        return OP.enabled()
    except Exception:  # pylint: disable=broad-except
        return False


def _forget_pieces(page_ids: list[int]) -> None:
    """The search pieces of deleted Context pages removed (in the background of this process when it can)."""
    if not page_ids:
        return
    from supagent import settings
    from supagent.knowledge import apply

    prefixes = ([f"context:{i}#" for i in page_ids] if len(page_ids) <= PAGE_SYNC_ONE_BY_ONE else ["context:"])
    try:
        if settings.get("knowledge.apply_background"):
            for p in prefixes:
                apply.later("chunks", prefix=p)
            apply.later("llm_context")
        else:
            apply.run({"prefixes": set(prefixes), "llm_context": True})
    except Exception:  # pylint: disable=broad-except   (the hourly indexing catches up)
        from superset import db

        db.session.rollback()
        log.warning("supagent: the search pieces of %s deleted pages: not removed yet", len(page_ids), exc_info=True)


def write_pages(source: str, refs: list[str]) -> dict[str, Any]:
    """(in the background) The pages of these dashboards written again from their source, no LLM; ("" in `refs`:
    OpenSearch Dashboards' pages of the visualizations on no dashboard read, too); their search pieces written at
    once (found by words now, by meaning as soon as their vectors are made)."""
    from superset import db

    from supagent.models import ContextPage

    if source == "grafana":
        from supagent.knowledge import grafana_pages as GP

        out = GP.refresh(llm=False, only=set(refs))
        lone_prefix = None
    else:
        from supagent.knowledge import osd_pages as OP

        out = OP.refresh(llm=False, only=set(refs))
        lone_prefix = OP.LONE if "" in refs else None
    slugs = page_slugs(source, [r for r in refs if r])
    q = db.session.query(ContextPage.id).filter(ContextPage.slug.in_(slugs or ["-"]))
    ids = {i for (i,) in q}
    if lone_prefix:
        ids |= {i for (i,) in db.session.query(ContextPage.id).filter(ContextPage.slug.like(lone_prefix + "%"))}
    from supagent.knowledge.index import embed_few, sync

    prefixes = tuple(f"context:{i}#" for i in sorted(ids)) if len(ids) <= PAGE_SYNC_ONE_BY_ONE else ("context:",)
    if lone_prefix:                                     # lone pages gone: their pieces too
        prefixes = ("context:",)
    if prefixes:
        written = sync(prefixes)
        embed_few(written)
        out["search"] = {k: v for k, v in written.items() if isinstance(v, int)}
    return out


# --------------------------------------------------------------------------------------------------------------- #
# the jobs: list now, pages written again
# --------------------------------------------------------------------------------------------------------------- #
def job(source: str) -> dict[str, Any]:
    from superset import db

    from supagent.models import Meta

    try:
        row = db.session.get(Meta, JOB + source)
        got = json.loads(row.value) if row is not None and row.value else {}
    except Exception:  # pylint: disable=broad-except
        db.session.rollback()
        return {}
    if got.get("running") and time.time() - float(got.get("t0") or 0) > STALE_JOB:
        got.update(running=False, error=got.get("error") or "stopped (its process ended)")
    return got


def _job(source: str, **values: Any) -> None:
    from superset import db

    from supagent.models import Meta

    row = db.session.get(Meta, JOB + source) or Meta(key=JOB + source)
    try:
        got = json.loads(row.value) if row.value else {}
    except ValueError:
        got = {}
    got.update(values)
    row.value = json.dumps(got, default=str)[:20000]
    db.session.merge(row)
    db.session.commit()


def run_job(source: str, what: str, refs: list[str] | None = None) -> dict[str, Any]:
    """(the background) `what` list: the list read now (no LLM, no page); pages: the pages of `refs` written again."""
    from superset import db

    t0 = time.time()
    _job(source, what=what, running=True, t0=t0, started=_now().isoformat() + "Z", error=None, stats=None)
    try:
        if what == "list":
            stats = listing(source)
        else:
            stats = write_pages(source, list(refs or []))
        _job(source, running=False, done=_now().isoformat() + "Z", seconds=round(time.time() - t0, 1),
             stats=stats, error=stats.get("error") if isinstance(stats, dict) else None)
        return stats
    except Exception as ex:  # pylint: disable=broad-except
        db.session.rollback()
        log.warning("supagent: %s %s", source, what, exc_info=True)
        _job(source, running=False, done=_now().isoformat() + "Z", error=f"{type(ex).__name__}: {str(ex)[:300]}")
        return {"error": str(ex)[:300]}


def listing(source: str) -> dict[str, Any]:
    """The list read now from the source (no LLM, no page written)."""
    if source == "grafana":
        from supagent.knowledge import grafana_pages as GP

        return GP.listing()
    from supagent import osd

    return osd.listing()


# --------------------------------------------------------------------------------------------------------------- #
# the data dictionary's descriptions of the fields a visualization reads
# --------------------------------------------------------------------------------------------------------------- #
def field_notes(pattern: str, fields: Iterable[str]) -> dict[str, str]:
    """The data dictionary's description of each field (a .keyword sub-field: its field's) of the indices an index
    pattern reads (live objects only)."""
    from superset import db

    from supagent.models import KObject

    names = {str(f) for f in fields if f}
    if not names or not pattern:
        return {}
    wanted = names | {n[:-8] for n in names if n.endswith(".keyword")}
    globs = [p.strip() for p in str(pattern).split(",") if p.strip() and not p.strip().startswith("-")]
    parents = set()
    for (name,) in db.session.query(KObject.name).filter(KObject.kind == "index", KObject.gone_at.is_(None)):
        if any(fnmatch.fnmatchcase(str(name), g) or str(name) == g for g in globs):
            parents.add(str(name))
    if not parents:
        return {}
    out: dict[str, str] = {}
    rows = db.session.query(KObject.name, KObject.description, KObject.backend_help).filter(
        KObject.kind == "field", KObject.parent.in_(sorted(parents)), KObject.name.in_(sorted(wanted)),
        KObject.gone_at.is_(None))
    found: dict[str, str] = {}
    for name, desc, helptext in rows:
        text = " ".join(str(desc or helptext or "").split())[:200]
        if text and name not in found:
            found[str(name)] = text
    for n in names:
        base = n[:-8] if n.endswith(".keyword") else n
        if n in found or base in found:
            out[n] = found.get(n) or found[base]
    return out
