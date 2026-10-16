"""(0.10.11.1) The chats, for the command line: list them (with what their answers keep for the page) and delete them,
as the chat's own Delete does (its messages, their files and the examples taken from them)."""
from __future__ import annotations

from typing import Any


def listed(user_id: int | None = None, limit: int = 30, ids: list[int] | None = None) -> list[dict[str, Any]]:
    """The chats, the latest first (`ids`: those only): id, user, title, updated, messages, the size of what their
    answers keep (counted by the database: a chat too big to open is listed without being read)."""
    import sqlalchemy as sa
    from superset import db, security_manager

    from supagent.models import Conversation, Message

    q = db.session.query(Conversation)
    if user_id is not None:
        q = q.filter(Conversation.user_id == user_id)
    if ids is not None:
        q = q.filter(Conversation.id.in_(list(ids) or [0]))
    convs = q.order_by(Conversation.updated_at.desc()).limit(limit).all()
    size = (sa.func.coalesce(sa.func.length(Message.content), 0) +
            sa.func.coalesce(sa.func.length(sa.cast(Message.steps, sa.Text)), 0) +
            sa.func.coalesce(sa.func.length(sa.cast(Message.results, sa.Text)), 0))
    live = sa.case((Message.status.in_(("pending", "running", "cancelling")), 1), else_=0)
    stats = {cid: (n, b, r) for cid, n, b, r in
             db.session.query(Message.conversation_id, sa.func.count(Message.id), sa.func.sum(size), sa.func.sum(live))
             .filter(Message.conversation_id.in_([c.id for c in convs] or [0])).group_by(Message.conversation_id)}
    out = []
    for c in convs:
        n, b, r = stats.get(c.id, (0, 0, 0))
        user = security_manager.get_user_by_id(c.user_id)
        out.append({"id": c.id, "user": getattr(user, "username", c.user_id), "title": c.title or "",
                    "updated_at": c.updated_at, "messages": int(n or 0), "bytes": int(b or 0), "running": int(r or 0)})
    return out


def delete(ids: list[int]) -> int:
    """Delete these chats with their messages, files and examples; the number deleted."""
    from superset import db

    from supagent.models import Conversation, Example, File, Message

    n = 0
    for cid in ids:
        conv = db.session.get(Conversation, cid)
        if conv is None:
            continue
        mids = [m.id for m in db.session.query(Message.id).filter_by(conversation_id=cid)]
        if mids:
            db.session.query(File).filter(File.message_id.in_(mids)).delete(synchronize_session=False)
            db.session.query(Example).filter(Example.message_id.in_(mids)).delete(synchronize_session=False)
            db.session.query(Message).filter(Message.id.in_(mids)).delete(synchronize_session=False)
        db.session.delete(conv)
        n += 1
    db.session.commit()
    return n
