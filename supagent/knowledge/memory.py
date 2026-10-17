"""Preferences, rules and facts learned from the chats, for a user or for the team.

Learned only on explicit signals (never from every chat: a wrong rule would change everyone's
answers, and the LLM is shared): an answer marked Helpful, or a question that says "always",
"from now on", "remember", "by default", "toujours", "désormais", "retiens", "par défaut"...
The LLM extracts the durable points of that exchange; a user can also add or delete their own.

Personal memories are used at once, in their author's answers only. Team memories are used
after an admin's approval (memory.team_approval, default) or at once when approval is off.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from superset import db

from supagent import settings
from supagent.models import Conversation, Memory, Message

log = logging.getLogger(__name__)
SIGNALS = re.compile(r"\b(always|never|from now on|remember|by default|in future|keep in mind|i prefer|we prefer|"
                     r"memory|memori[sz]e|note (?:it|that)|when i say|you should know|"
                     r"toujours|jamais|d[ée]sormais|dor[ée]navant|retiens|souviens|par d[ée]faut|je pr[ée]f[èe]re|"
                     r"nous pr[ée]f[ée]rons|à l'avenir|m[ée]moire|m[ée]moris\w*|quand je dis|tu dois savoir)\b", re.I)
PROMPT = """You keep the memory of a data assistant used by a team. From the exchange below, list
only DURABLE points worth remembering for later questions: how this user or the team wants
answers (format, units, sorting, time zone, what 'yesterday' or 'today' means, environments to
exclude...), business rules and definitions stated by the user, facts about the data the user
asserted. Do not list what the assistant found in the data (results change), nor one-off
requests: an instruction for this question only ("compute it as X", "for 23 September", "as a
table") is not durable unless the user says it applies from now on, always, or to everyone.
Answer with a JSON list only (empty list when nothing is durable):
[{"text": "...", "scope": "personal" or "team", "kind": "preference" or "rule" or "fact",
  "category": "a short topic"}]
scope "team" only when the user says it applies to everyone or states a business rule.
When the assistant asked the user what a word meant and the user answered, the answer is a
definition worth keeping (team, fact, when it says what a business word or a field means). When
the user marked the answer Not helpful and said why, keep what the reason says about the data or
how to compute it (a rule or a definition: team), not a complaint."""


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9àâçéèêëîïôûùüÿœ]+", (text or "").lower()))


def _similar(a: str, b: str) -> bool:
    wa, wb = set(_norm(a).split()), set(_norm(b).split())
    if not wa or not wb:
        return False
    return len(wa & wb) / max(len(wa), len(wb)) >= 0.8


SAVED_CHARS = 20000        # (0.10.9.1) of a memory as saved, at most (was 1000: a memory is kept as written)


def add(user_id: int, text: str, scope: str = "user", kind: str = "preference", category: str | None = None,
        source: str = "manual", message_id: int | None = None, approved_by: str | None = None,
        group_id: int | None = None) -> Memory | None:
    """A memory (None when an equivalent one exists). Never a second copy: a person writing again a
    memory that was disabled brings it back (for the team: to approve again); one learned from a chat
    that someone disabled stays disabled (it was refused)."""
    text = (text or "").strip()
    if not text:
        return None
    scope = "team" if scope in ("team", "everyone") else "group" if scope == "group" and group_id else "user"
    q = db.session.query(Memory)
    q = q.filter(Memory.scope == "team") if scope == "team" else \
        q.filter(Memory.scope == "group", Memory.group_id == group_id) if scope == "group" else \
        q.filter(Memory.scope == "user", Memory.user_id == user_id)
    same = [m for m in q.limit(5000) if _similar(m.text, text)]
    status = "active"
    if scope in ("team", "group") and settings.get("memory.team_approval") and not approved_by:
        status = "proposed"
    if same:
        kept = next((m for m in same if m.status != "disabled"), None)
        if kept is not None or source != "manual":
            return None
        m = same[0]                                     # written again by a person: back, not a copy
        m.status, m.text, m.approved_by = status, text[:SAVED_CHARS], approved_by
        m.kind = kind if kind in ("preference", "rule", "fact") else m.kind
        db.session.commit()
        return m
    m = Memory(scope=scope, user_id=user_id, kind=kind if kind in ("preference", "rule", "fact") else "preference",
               text=text[:SAVED_CHARS], category=(category or None), status=status, source=source,
               message_id=message_id,
               approved_by=approved_by, group_id=group_id if scope == "group" else None)
    db.session.add(m)
    db.session.commit()
    return m


QUESTION_START = re.compile(
    r"^\s*(what|which|who|whom|whose|when|where|why|how|is|are|do|does|did|can|could|would|will|should|show|give|"
    r"list|find|get|tell|display|draw|plot|compare|count|calculate|compute|explain|send|export|create|make|save|"
    r"need|i need|i want|i would|please|quel|quelle|quels|quelles|qui|quand|o[uù]|pourquoi|comment|combien|"
    r"est-ce|peux|pouvez|peut|donne|montre|affiche|liste|trouve|calcule|compare|envoie|exporte|cr[ée]e|fais|"
    r"j'ai besoin|je veux|je voudrais)\b", re.I)
DECLARATIVE = re.compile(r"\b(is|are|means|mean|equals|stands for|refers to|corresponds to|contains|holds|represents|"
                         r"est|sont|signifie|veut dire|correspond|contient|d[ée]signe|repr[ée]sente)\b|=", re.I)


def is_statement(text: str) -> bool:
    """A message that tells something (the field X means Y, KO = failed), not a question: what it
    says about the data is worth keeping (the LLM extracts it; team facts wait for an admin)."""
    t = (text or "").strip()
    if not t or "?" in t or len(t) > 1500 or QUESTION_START.search(t):
        return False
    return bool(DECLARATIVE.search(t))


# (0.10.9.1) a message that asks to remember something: what follows the request is kept as written, before the
# answer (it applies to this answer already), and no LLM rewrites it
REMEMBER = re.compile(r"^\s*(?:please\s+|pls\s+|stp\s+|svp\s+|merci\s+de\s+)?(?:remember|memori[sz]e|keep\s+in\s+mind|"
                      r"don'?t\s+forget|do\s+not\s+forget|note\s+(?:that|this|it)|retiens|souviens[- ]toi|"
                      r"n'oublie\s+pas|m[ée]morise|garde\s+en\s+m[ée]moire|note\s+bien)\b\s*(?:[,:;-]\s*)?"
                      r"(?:that\s+|que\s+|qu')?(?P<text>\S.*)$", re.I | re.S)
# "... and show me X", "..., then give the total": a request in the same message (not only something to remember)
ALSO_ASKED = re.compile(r"(?:\band\b|\bthen\b|\bpuis\b|\bet\b|,)\s+(?:please\s+|stp\s+)?(?:show|give|list|tell|"
                        r"compute|calculate|count|find|draw|plot|make|create|send|export|check|run|what|which|how|"
                        r"montre|donne|liste|calcule|trouve|affiche|dis|cr[ée]e|envoie|v[ée]rifie|quel|combien)\b",
                        re.I)
RULE_WORDS = re.compile(r"\b(always|never|must|do not|don't|only|toujours|jamais|doit|doivent|uniquement|seulement)\b",
                        re.I)


def remember_request(message: str) -> str | None:
    """(0.10.9.1) The words to remember when the message asks to remember them ("Remember that X", "Retiens que X",
    "Keep in mind: X"), as written; None for any other message (a question about the past: "remember what we did?")."""
    m = REMEMBER.match(message or "")
    if m is None:
        return None
    text = m.group("text").strip()
    if not text or "?" in text or QUESTION_START.match(text) and not DECLARATIVE.search(text):
        return None
    if ALSO_ASKED.search(text) or any(QUESTION_START.match(x) for x in re.split(r"(?<=[.;!])\s+|\n+", text)[1:]):
        return None                                    # it asks something too: the answer's own words (the LLM
    return text                                        # keeps the durable point after it, as before)


def remember_now(user_id: int | None, message: str) -> Memory | None:
    """(0.10.9.1) A message asking to remember something: kept now, as written, as the user's own memory (active at
    once: this answer is given it already). None when it asks nothing of the kind, or it is remembered already."""
    text = remember_request(message)
    if user_id is None or text is None or not settings.get("memory.enabled"):
        return None
    kind = "rule" if RULE_WORDS.search(text) else "fact" if DECLARATIVE.search(text) else "preference"
    m = add(user_id, text, scope="user", kind=kind, source="manual")
    if m is not None:
        try:
            from supagent.knowledge.index import sync

            sync(("memory:",))                         # found by the search too (its words; embedded later)
        except Exception:  # pylint: disable=broad-except   (the prompt has it anyway)
            db.session.rollback()
    return m


def worth_learning(question: str) -> bool:
    return bool(SIGNALS.search(question or "")) or is_statement(question)


def learn_from_message(message_id: int, llm: Any = None) -> list[int]:
    """The durable points of the exchange that ends with this answer."""
    from supagent.llm import LLM

    if not settings.get("memory.enabled"):
        return []
    answer = db.session.get(Message, message_id)
    if answer is None or answer.role != "assistant":
        return []
    conv = db.session.get(Conversation, answer.conversation_id)
    question = (db.session.query(Message).filter(Message.conversation_id == answer.conversation_id,
                                                 Message.id < message_id, Message.role == "user")
                .order_by(Message.id.desc()).first())
    if conv is None or question is None:
        return []
    exchange = f"USER: {question.content[:3000]}\nASSISTANT: {(answer.content or '')[:3000]}"
    asked = asked_back(question)
    if asked is not None:                              # the user answered a question of the assistant
        first, back = asked
        exchange = (f"USER: {first.content[:2000]}\nASSISTANT (asking what the user meant): {back.content[:1500]}\n"
                    + exchange)
    if answer.feedback == -1 and answer.feedback_reason:
        exchange += f"\nUSER (marked this answer Not helpful): {answer.feedback_reason[:1000]}"
    from supagent.llm import llm_task

    try:
        with llm_task("memory", user_id=conv.user_id, message_id=message_id):
            msg = (llm or LLM()).chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": exchange}],
                                      max_tokens=600)
    except Exception as ex:  # pylint: disable=broad-except
        log.warning("supagent memory: %s", ex)
        return []
    text = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S)
    start, end = text.find("["), text.rfind("]")
    try:
        items = json.loads(text[start:end + 1]) if 0 <= start < end else []
    except ValueError:
        items = []
    made = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not str(it.get("text") or "").strip():
            continue
        m = add(conv.user_id, str(it["text"]), scope="team" if it.get("scope") == "team" else "user",
                kind=str(it.get("kind") or "preference"), category=it.get("category"), source="chat",
                message_id=message_id)
        if m is not None:
            made.append(m.id)
    if made:
        from supagent.knowledge.index import embed_few, sync

        embed_few(sync(("memory:",)))
    return made


def asked_back(question: Message) -> tuple[Message, Message] | None:
    """(the user's question before, the assistant's question back) when `question` answers what
    the assistant asked (rule 6 of the agent)."""
    from supagent.agent import asks_back

    back = (db.session.query(Message).filter(Message.conversation_id == question.conversation_id,
                                             Message.id < question.id).order_by(Message.id.desc()).first())
    if back is None or back.role != "assistant" or not asks_back(back.content or ""):
        return None
    first = (db.session.query(Message).filter(Message.conversation_id == question.conversation_id,
                                              Message.id < back.id, Message.role == "user")
             .order_by(Message.id.desc()).first())
    return (first, back) if first is not None else None


def memories_for(user_id: int | None, limit: int | None = None, groups: list[int] | None = None) -> list[Memory]:
    """The user's personal memories, the team's active ones and those of the user's groups (for the prompt): all of
    them ((0.10.9.1) a memory is never left out; `limit` per scope only when a caller asks for fewer)."""
    if groups is None:
        from supagent.security import user_groups

        groups = [x.id for x in user_groups()]
    q = db.session.query(Memory).filter(Memory.status == "active")
    mine = q.filter(Memory.scope == "user", Memory.user_id == user_id).order_by(Memory.id.desc()).limit(limit).all() \
        if user_id is not None else []
    team = q.filter(Memory.scope == "team").order_by(Memory.id.desc()).limit(limit).all()
    group = q.filter(Memory.scope == "group", Memory.group_id.in_(groups or [-1])).order_by(
        Memory.id.desc()).limit(limit).all()
    return mine + group + team


def triggered(text: str, asked: str) -> bool:
    """(0.10.7) A memory that says when it applies ("When the user says 'X' ...", "Quand je dis X ...") applies when
    the question or the chat says X; any other memory always."""
    from supagent.knowledge.conditions import TRIGGER

    t = TRIGGER.search(text or "")
    if t is None:
        return True
    trigger = (t.group(1) or t.group(2) or "").strip().lower()
    return not trigger or trigger in (asked or "").lower()


KIND_ORDER = {"rule": 0, "preference": 1, "fact": 2}
ENTRY_CHARS = 400          # (until 0.10.9) of each memory in the prompt; since 0.10.9.1 a memory is given whole


def prompt_block(user_id: int | None, shown: set[str] | None = None, asked: str | None = None,
                 said: list[str] | None = None) -> str:
    """The memories given with every question, first of what is found for it: rules, then preferences, then facts
    (the user's own first, the newest first). (0.10.9.1) Each one whole and as written (its lines kept), and every one
    of them: none is left out to make room for the rest, the knowledge found gives way (memory.prompt_chars is their
    room before it does). `shown` gets the refs of the ones given, not given twice. (0.10.7) With `asked` (the
    question and the chat), a memory that applies only when the user says X ("When the user says 'X', filter by
    F='X'") is not given when they do not say X: told "applies only then", a model still filtered a question that
    never named X. (0.11.0) With `said` (the team's rules the instructions give), each memory is given once: a copy of
    another, or one said whole by another or by a rule, is left out (knowledge.contextplan; memories alike but not the
    same are both given, and listed in To review)."""
    items = memories_for(user_id)
    if not items:
        return ""
    if said is not None:
        from supagent.knowledge.contextplan import unique

        order = sorted(items, key=lambda m: KIND_ORDER.get(m.kind, 3))
        live = [m for m in order if asked is None or triggered(m.text, asked)]
        keep, _dropped = unique([(m.id, m.text or "") for m in live], said=said)
        keep_ids = set(keep)
        if shown is not None:
            shown.update(f"memory:{m.id}" for m in live if m.id not in keep_ids)   # said: not found again either
        items = [m for m in items if m.id in keep_ids or m not in live]
    from supagent.knowledge.resolve import gone_names, mentions_gone

    gone = gone_names()
    lines = ["\n\nWhat this user and the team asked to remember (follow it unless the chat says otherwise: a unit or "
             "a format the question or an earlier message of this chat asks for (\"in seconds\", \"in hours, please\", "
             "\"as a table\") is the one to answer in, whatever a memory prefers; a memory about one kind of figure "
             "(how long something took, a size, an amount) is about that kind only, and one that does not apply to "
             "this answer is left unsaid; one that says when it applies (\"when the user says X\", \"for the desk Y\") applies only then: it "
             "is no filter for a question that does not say X):"]
    for m in sorted(items, key=lambda m: KIND_ORDER.get(m.kind, 3)):     # stable: mine, then the team's
        if asked is not None and not triggered(m.text, asked):
            continue                                   # (0.10.7) "when the user says X" and X not said: it applies
        #                                                only then (given always, a model filtered by X anyway)
        who = "team" if m.scope == "team" else "this user's team" if m.scope == "group" else "this user"
        text = "\n  ".join(ln.rstrip() for ln in (m.text or "").strip().splitlines() if ln.strip())   # as written
        line = f"- ({who}, {m.kind}) {text}"
        if mentions_gone(m.text, gone):                # (0.10.9.1) about a metric or an index that no longer exists:
            said = sorted({w for w in re.findall(r"[A-Za-z0-9_:.@\-]+", m.text or "") if w in gone})   # given all
            line += f" (it names data that no longer exists: {', '.join(said[:5])})"   # the same, said so: a memory
        #                                                                                is never left out
        lines.append(line)
        if shown is not None:
            shown.add(f"memory:{m.id}")
    return "\n".join(lines) if len(lines) > 1 else ""


STATUS_RANK = {"active": 0, "catalog": 1, "proposed": 2, "disabled": 3}


def merge_duplicates() -> int:
    """Copies of a memory (the same words, the same scope and, for a personal one, the same user): one
    stays (active first, then the newest), the others are deleted. Returns how many were deleted."""
    groups: dict[tuple, list[Memory]] = {}
    for m in db.session.query(Memory):
        key = (m.scope, m.user_id if m.scope == "user" else None, _norm(m.text))
        groups.setdefault(key, []).append(m)
    gone = 0
    for same in groups.values():
        if len(same) < 2:
            continue
        same.sort(key=lambda m: (STATUS_RANK.get(m.status or "", 4), -(m.id or 0)))
        for m in same[1:]:
            db.session.delete(m)
            gone += 1
    if gone:
        db.session.commit()
    return gone
