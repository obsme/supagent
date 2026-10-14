"""(0.10.9.1) A field, a label, a metric or an index the team deactivates in the Data dictionary: the agent and the
search never see it nor use it. It is kept as the dictionary's own "gone" objects are (gone_at), at a mark of its own
(DEACTIVATED), so that every reader of the live objects leaves it out, and the learning, seeing it again, leaves it
deactivated. Deactivating an index or a metric deactivates its fields or labels with it; activating it again brings
back those it took. A query naming a deactivated object is sent back before it runs."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from superset import db

from supagent.models import KObject

DEACTIVATED = dt.datetime(1970, 1, 1)      # the gone_at of a deactivated object (a real gone time is never this)
CHILD_KIND = {"index": "field", "family": "field", "metric": "label"}


def is_deactivated(o: Any) -> bool:
    return getattr(o, "gone_at", None) == DEACTIVATED


def alive(o: Any) -> None:
    """The learning saw the object again: alive, unless the team deactivated it."""
    if not is_deactivated(o):
        o.gone_at = None


def set_active(o: KObject, active: bool) -> int:
    """Deactivate (active False) or activate an object, with its fields or labels; how many objects changed."""
    kids = []
    if o.kind in CHILD_KIND:
        kids = db.session.query(KObject).filter(KObject.source_id == o.source_id, KObject.parent == o.name,
                                                KObject.kind == CHILD_KIND[o.kind]).all()
    n = 0
    for x in [o] + kids:
        if not active and x.gone_at is None:
            x.gone_at, n = DEACTIVATED, n + 1
        elif active and is_deactivated(x):
            x.gone_at, n = None, n + 1
    return n


def deactivated() -> list[KObject]:
    return db.session.query(KObject).filter(KObject.gone_at == DEACTIVATED).all()


def refusal(tool: str, args: dict) -> str | None:
    """A query that reads a deactivated index or metric, or names a deactivated field or label of what it reads."""
    from supagent.knowledge.rulecheck import QUERY_TOOLS, _tables

    if tool not in QUERY_TOOLS:
        return None
    off = deactivated()
    if not off:
        return None
    from supagent.knowledge.excluded import query_texts

    said: list[str] = []
    for text in query_texts(args or {}):
        tables = {t.lower() for t in _tables(text)}
        low = text.lower()
        for o in off:
            if o.kind in ("index", "family", "metric") and o.name.lower() in tables:
                said.append(f"the {o.kind} {o.name}")
            elif o.kind in ("field", "label") and (o.parent or "").lower() in tables and \
                    re.search(r"(?<![\w.])" + re.escape(o.name.lower()) + r"(?![\w])", low):
                said.append(f"the {o.kind} {o.name} of {o.parent}")
    if not said:
        return None
    return ("tool error (not run: deactivated): the team deactivated " + ", ".join(dict.fromkeys(said)) + " in the "
            "Data dictionary: it is not to be used. Answer from the other data, or say that it is not available.")
