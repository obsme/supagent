"""(0.10.9.1) What the Data dictionary's pages compute from the whole knowledge and show again on every load (the
warnings of To review, where the categories are in the data, what investigations still lack): kept per process until
the knowledge changes, or for at most TTL seconds. On a big deployment each took seconds, and opening the Data
dictionary asked for them twice (the To review badge, then the tab).

"The knowledge changed" is a stamp every process reads (supagent_meta, KEY): written after any commit that adds,
changes or removes what these pages read (a value, a link, an item's category, a document, a catalog entry, a Context
page, a setting, an investigation path), one by one or in bulk, in the web server or in a Celery worker; plus the
last run (a learning, a Context build, a classification), for what only a run writes (the data's fields). A page
reads it once per request: a change made on one web worker is seen by the next request on another. What a person
sets aside (a warning, a field proposal: supagent_meta) is read at each request, not kept.

    cached("lint", warnings)        the value, computed again only when the knowledge changed
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

TTL = 300.0                    # seconds: what no stamp follows (a database's access rights) shows within 5 minutes
KEY = "pages_changed"          # supagent_meta: when the knowledge these pages read last changed, for every process
WATCHED = ("Facet", "Link", "Tag", "Doc", "Entry", "ContextPage", "Setting", "Recipe")
SIZE = 64                      # values kept at most (one per name; the fields' per set of databases a user reads)
_FLAG = "supagent_pages_changed"
_CACHE: dict[str, tuple[Any, float, Any]] = {}
_LOCK = threading.Lock()
_OWN = [0]                     # this process's own changes: seen at once, whatever becomes of the stamp's write


def _kinds() -> tuple[type, ...]:
    from supagent import models

    return tuple(getattr(models, n) for n in WATCHED)


def _mark(session: Any, _ctx: Any, _instances: Any) -> None:
    """Before a flush: a watched row added, changed or removed."""
    try:
        kinds = _kinds()
        if any(isinstance(o, kinds) for o in (*session.new, *session.dirty, *session.deleted)):
            session.info[_FLAG] = True
    except Exception:  # pylint: disable=broad-except
        pass


def _mark_bulk(state: Any) -> None:
    """An UPDATE or a DELETE of many rows at once (query(...).update(), .delete()): not among the session's objects."""
    try:
        if (state.is_update or state.is_delete) and any(
                issubclass(m.class_, _kinds()) for m in state.all_mappers):
            state.session.info[_FLAG] = True
    except Exception:  # pylint: disable=broad-except
        pass


def _stamp(session: Any) -> None:
    """After a commit that changed the knowledge: the stamp written in a short transaction of its own (as the map's,
    index._stamp_map: a long learning run must not hold the row)."""
    if not session.info.pop(_FLAG, False):
        return
    _OWN[0] += 1
    import sqlalchemy as sa

    value = f"{time.time():.6f}"
    try:
        with session.get_bind().begin() as con:
            done = con.execute(sa.text("UPDATE supagent_meta SET value = :v WHERE key = :k"),
                               {"v": value, "k": KEY}).rowcount
            if not done:
                con.execute(sa.text("INSERT INTO supagent_meta (key, value) VALUES (:k, :v)"), {"k": KEY, "v": value})
    except Exception as ex:  # pylint: disable=broad-except   (another process wrote it at the same time, or no table)
        log.debug("supagent: the pages' stamp: %s", ex)


def _forget(session: Any) -> None:
    session.info.pop(_FLAG, None)


try:
    from sqlalchemy import event as _event
    from sqlalchemy.orm import Session as _Session

    _event.listen(_Session, "before_flush", _mark)
    _event.listen(_Session, "do_orm_execute", _mark_bulk)
    _event.listen(_Session, "after_commit", _stamp)
    _event.listen(_Session, "after_rollback", _forget)
except Exception:  # pylint: disable=broad-except
    log.warning("supagent: the Data dictionary's pages are computed at every load", exc_info=True)


def stamp() -> Any:
    """What says the knowledge changed (None: unknown, nothing is kept)."""
    from superset import db

    from supagent.models import Meta, Run

    try:
        value = db.session.query(Meta.value).filter(Meta.key == KEY).scalar()
        last = db.session.query(Run.id, Run.status, Run.finished_at).order_by(Run.id.desc()).first()
    except Exception:  # pylint: disable=broad-except   (tables not created yet)
        db.session.rollback()
        return None
    return (_OWN[0], value, tuple(last) if last else None)


def cached(name: str, compute: Callable[[], Any], ttl: float = TTL) -> Any:
    """compute()'s value, kept until the stamp changes or for ttl seconds. Shared: its callers do not change it."""
    key = stamp()
    now = time.time()
    if key is not None:
        with _LOCK:
            hit = _CACHE.get(name)
        if hit is not None and hit[0] == key and now - hit[1] < ttl:
            return hit[2]
    value = compute()
    if key is not None:
        with _LOCK:
            _CACHE[name] = (key, now, value)
            while len(_CACHE) > SIZE:
                _CACHE.pop(min(_CACHE, key=lambda n: _CACHE[n][1]))
    return value


def clear() -> None:
    with _LOCK:
        _CACHE.clear()
