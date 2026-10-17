"""(0.11.0) The learning's history, kept for learn.history_days (30 by default; the owner's request of 2026-10-17:
"automatic suppression of learning history after 30 days"): the runs (the daily learning, the classification, the
Context, the backups and restores, the documents' reads) finished before that are removed every hour by the workers'
tick, with what each found changed (supagent_change). The last run of each kind is kept whatever its age (the pages
say when it was), and a run still going is never removed. The knowledge itself (the catalog's versions, the Context's
pages, the learned answers) is not history: kept."""
from __future__ import annotations

import datetime as dt
import logging

import sqlalchemy as sa
from superset import db

log = logging.getLogger(__name__)

BATCH = 5000                # runs removed per pass at most (the next tick goes on)
LIVE = ("running", "stopping")


def purge(days: int | None = None, now: dt.datetime | None = None) -> dict[str, int]:
    """Remove the runs finished more than `days` ago (learn.history_days when None; 0: none) and their changes."""
    from supagent import settings
    from supagent.models import Change, Run

    if days is None:
        days = int(settings.get("learn.history_days") or 0)
    if days <= 0:
        return {"runs": 0, "changes": 0}
    limit = (now or dt.datetime.utcnow()) - dt.timedelta(days=days)
    last = [r[0] for r in db.session.query(sa.func.max(Run.id)).group_by(Run.kind)]
    ended = sa.func.coalesce(Run.finished_at, Run.started_at)
    ids = [r[0] for r in db.session.query(Run.id).filter(Run.status.notin_(LIVE), ended < limit,
                                                          Run.id.notin_(last or [-1]))
           .order_by(Run.id).limit(BATCH)]
    changes = 0
    if ids:
        changes = db.session.query(Change).filter(Change.run_id.in_(ids)).delete(synchronize_session=False)
    changes += db.session.query(Change).filter(Change.run_id.is_(None), Change.at < limit).delete(
        synchronize_session=False)
    runs = db.session.query(Run).filter(Run.id.in_(ids)).delete(synchronize_session=False) if ids else 0
    db.session.commit()
    if runs or changes:
        log.info("supagent: learning history older than %s days removed: %s runs, %s changes", days, runs, changes)
    return {"runs": runs, "changes": changes}
