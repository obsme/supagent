"""(0.11.0) The agent's context in three tiers (the owner's request of 2026-10-17: the catalog, the memories and what
the agent learned taken in first, cleaned of duplicates and almost similar inputs; then the conversation; then the
documentation, chosen with care, never all of it).

  1. what the team keeps: the catalog's rules (in the instructions), the memories, the team's words, where the data
     is, the learned answers: given whole, each said once;
  2. the chat: the last complete exchange always, then the older messages, the newest first, in the room the first
     tier leaves, never starting with an answer;
  3. the documentation: the knowledge found for the question and the lines of the LLM context about it (never the
     whole page: a line about nothing the question names is not given, however much room is left).

Two texts say the same when they hold the same words in the same order once case, punctuation, plurals and small
words are set aside ("Always give durations in minutes, please." and "Give durations in minutes"): then one is given.
Anything that changes what a text says keeps both: another word (a qualifier: "failed jobs"; a condition: "for the
desk Y"), a negation ("don't" is "do not"), an operator or a sign ("> 500" and "< 500", "UTC -2" and "UTC +2"), a modal
verb ("must", "may"), a quoted value as written ('FAILED' and 'failed'). Texts alike but not the same are both kept
and listed in To review (lint: duplicates), for a person to decide. No LLM."""
from __future__ import annotations

import re
from typing import Any, Iterable

WORD = re.compile(r"[a-z0-9\u00c0-\u024f]+(?:[-_.:@/][a-z0-9\u00c0-\u024f]+)*")
# (0.11.0, after the review) the words of a text as compared: an operator, a signed number and a quoted value (its
# case kept) are words of their own; "n't" is "not"
TOKEN = re.compile(r"(<=|>=|!=|==|<>|[<>=])|((?<![\w])[+-]\d+(?:[.,]\d+)*)|"
                   r"([A-Za-z0-9\u00c0-\u024f]+(?:[-_.:@/][A-Za-z0-9\u00c0-\u024f]+)*)")
QUOTED = re.compile(r"[\"'\u2018\u2019\u201c\u201d\u00ab\u00bb`]([^\"'\u2018\u2019\u201c\u201d\u00ab\u00bb`\n]{1,80})"
                    r"[\"'\u2018\u2019\u201c\u201d\u00ab\u00bb`]")
NOT = re.compile(r"\b(won|can|shan)['\u2019]t\b|n['\u2019]t\b", re.I)
STOP = frozenset("""a an the is are be been was were it its this that these those as please always also just then so
very really use using give given do does did
le la les un une des est sont il elle ce cet cette ces toujours merci svp""".split())
QUESTION_STOP = frozenset("""what which how many much who whom whose where when why there any can could show list tell
me us our we i you your find get did is are was were do does quel quelle quels quelles combien qui ou quand pourquoi
comment""".split())
# words that change what a text says: the question's words the LLM context's lines are not matched on
GUARD = frozenset("""on in at of by with from to into within across through via against and or
not no never none without except unless nor only when if for per each every after before during
between since until while where whose which who than more less greater smaller above below over under max min maximum
minimum average avg mean median sum total count top bottom first last latest oldest new old all any some most least
ms millisecond second sec minute min hour hr day week month year byte kb mb gb tb kib mib gib tib percent pct utc cet
cest gmt local today yesterday tomorrow
de du d l en au aux dans sur et ou
ne pas jamais sans sauf aucun seulement quand si pour par chaque apres avant pendant entre depuis plus moins tous""".split())
ALIKE = 0.7                 # the share of words two texts have in common from which To review lists them as alike


def _stem(w: str) -> str:
    if len(w) > 3 and w.isalpha() and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def words(text: str) -> list[str]:
    """The words of a text that say something, in their order: case, punctuation, plurals and small words set aside,
    but never a negation ("don't" is "do not"), an operator (>, <=, !=), a sign (-2, +2), a modal verb (must, may) or
    the case of a quoted value ('FAILED' is not 'failed')."""
    text = NOT.sub(lambda m: {"won": "will", "can": "can", "shan": "shall"}.get((m.group(1) or "").lower(), "") + " not",
                   text or "")
    out: list[str] = []
    at = 0
    for q in QUOTED.finditer(text):
        out += _plain(text[at:q.start()])
        out += [f"'{t}" for t in (m.group(0) for m in TOKEN.finditer(q.group(1)))]    # as written
        at = q.end()
    return out + _plain(text[at:])


def _plain(text: str) -> list[str]:
    out = []
    for m in TOKEN.finditer(text):
        op, num, word = m.groups()
        if op or num:
            out.append(op or num)
            continue
        w = word.lower()
        if w not in STOP:
            out.append(_stem(w))
    return out


def same(a: str, b: str) -> bool:
    """Both texts say the same: the same words in the same order (see `words`)."""
    wa = words(a)
    return bool(wa) and wa == words(b)


def says(longer: str, shorter: str) -> bool:
    """(0.11.0, after the review) A text says another only when they are the same: a longer one adds something (a
    qualifier, a condition, a negation) that a copy would lose."""
    return same(longer, shorter)


def alike(a: str, b: str) -> float:
    """The share of words two texts have in common (0-1), for To review."""
    sa, sb = {w.lower() for w in words(a)}, {w.lower() for w in words(b)}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def unique(items: Iterable[tuple[Any, str]], said: Iterable[str] = ()) -> tuple[list[Any], dict[Any, Any]]:
    """(the keys kept in their order, {key left out: the key, or "said", that says it}) of `items` (key, text) given in
    their order of precedence: an item that says what one before it says (or a text of `said`, given already) is left
    out. One pass, by the words of each (no comparison of every pair)."""
    given = {tuple(words(t)) for t in said if t}
    first: dict[tuple, Any] = {}
    kept: list[Any] = []
    dropped: dict[Any, Any] = {}
    for key, text in items:
        w = tuple(words(text))
        if not w:
            kept.append(key)
            continue
        if w in given:
            dropped[key] = "said"
        elif w in first:
            dropped[key] = first[w]
        else:
            first[w] = key
            kept.append(key)
    return kept, dropped


# --------------------------------------------------------------------------------------------- #
# the chat
# --------------------------------------------------------------------------------------------- #
def fit_history(history: list[dict], room: int, each: int) -> list[dict]:
    """The chat's messages given with the question (the messages themselves, in their order): the last complete
    exchange always (the last question that was answered, and all after it), then the older ones, the newest first,
    while they fit `room` (each counted as cut to `each` characters); never starting with an answer."""
    items = [h for h in history or [] if h.get("content")]
    if not items:
        return []
    start = next((i for i in range(len(items) - 1, -1, -1) if items[i].get("role") == "user" and
                  any(x.get("role") == "assistant" for x in items[i + 1:])), max(0, len(items) - 2))
    used = sum(min(len(str(h["content"])), each) for h in items[start:])
    while start > 0:
        n = min(len(str(items[start - 1]["content"])), each)
        if used + n > room:
            break
        used += n
        start -= 1
    out = items[start:]
    while len(out) > 1 and out[0].get("role") != "user":
        out = out[1:]
    return out


# --------------------------------------------------------------------------------------------- #
# the documentation: the LLM context's lines about the question
# --------------------------------------------------------------------------------------------- #
ENTRY_MARK = re.compile(r"\s*<!-- e:(\d+) -->")
NAME = re.compile(r"`([^`\n]{2,120})`")
HEAD = re.compile(r"^- ((?:[^:`\n]|`[^`\n]*`)+?):(?: |$)")
MIN_SCORE = 2.0             # a line with less about the question is not given
BODY_WORDS = 40             # a line's words past its head count less the longer it is (a list of fields, a glossary)
NAME_SCORE = 3.0            # a name the question writes (orders-db, par1-b), found in the line


def _weights(lines: list[str]) -> dict[str, float]:
    """How much a word of the page tells (the rarer in the page, the more)."""
    import math

    seen: dict[str, int] = {}
    for line in lines:
        for w in set(words(line)):
            seen[w] = seen.get(w, 0) + 1
    n = max(1, len(lines))
    return {w: 1.0 + math.log(n / c) for w, c in seen.items()}


def _score(line: str, asked: set[str], names: set[str], weight: dict[str, float]) -> float:
    """How much a line of the LLM context is about the question: the question's words in its head (what it is about)
    count twice, in the rest less the longer the line; a name the question writes counts NAME_SCORE."""
    m = HEAD.match(line)
    head = m.group(1) if m else ""
    rest = line[m.end():] if m else line
    hw, rw = set(words(head)), words(rest)
    score = 2.0 * sum(weight.get(w, 1.0) for w in hw & asked)
    score += sum(weight.get(w, 1.0) for w in (set(rw) - hw) & asked) * min(1.0, BODY_WORDS / max(1, len(rw)))
    low = line.lower()
    return score + NAME_SCORE * sum(1 for n in names if n in low)


def excerpt(markdown: str, question: str, room: int, shown_titles: Iterable[str] = (), shown_ids: Iterable[int] = (),
            databases: Iterable[str] = ()) -> str:
    """The lines of the LLM context about the question, within `room` characters, in the page's order under their
    sections' headings: a line whose head names a word of the question, or that names much of it, or a name the
    question writes, or (the Data sections) the main data of a database the question is about; a line of an entry
    or a piece of data given already elsewhere (`shown_ids`, `shown_titles`) is left out. Nothing about the question:
    nothing."""
    if room <= 0 or not markdown:
        return ""
    raw = markdown.splitlines()
    body = [ln for ln in raw if ln.startswith("- ")]
    if not body:
        return ""
    weight = _weights(body)
    asked = {w for w in words(question) if w not in QUESTION_STOP and w not in GUARD}
    names = {n for n in WORD.findall((question or "").lower()) if any(c.isalpha() for c in n) and
             (any(c in n for c in "-_.:@/") or any(c.isdigit() for c in n))}
    dbs = {d.lower() for d in databases if d}
    ids = {int(i) for i in shown_ids}
    titles = {" ".join(words(t)) for t in shown_titles if t}
    named = {str(t).lower() for t in shown_titles if t}
    scored: list[tuple[float, int]] = []
    heading_of: dict[int, int] = {}
    heading = -1
    in_db = False
    for i, line in enumerate(raw):
        if line.startswith("## "):
            heading = i
            low = line.lower()
            in_db = low.startswith("## data: ") and any(f"## data: {d} (" in low for d in dbs)
            continue
        if not line.startswith("- "):
            continue
        heading_of[i] = heading
        m = ENTRY_MARK.search(line)
        if m and int(m.group(1)) in ids:
            continue
        head = HEAD.match(line)
        if head and " ".join(words(head.group(1))) in titles:
            continue                                 # an entry given already (by its title)
        own = NAME.findall(head.group(1)) if head else []
        if own and not line.startswith("- the ") and any(n.lower() in named for n in own):
            continue                                 # a piece of data the knowledge found gave already
        score = _score(line, asked, names, weight)
        if in_db and not line.startswith("- the "):    # a main object of a database the question is about
            score += MIN_SCORE
        if score >= MIN_SCORE:
            scored.append((score, i))
    if not scored:
        return ""
    chosen: set[int] = set()
    used = 0
    for score, i in sorted(scored, key=lambda x: (-x[0], x[1])):
        text = ENTRY_MARK.sub("", raw[i])
        h = heading_of.get(i, -1)
        extra = len(text) + 1 + (len(raw[h]) + 2 if h >= 0 and h not in chosen else 0)
        if used + extra > room:
            continue
        chosen.add(i)
        if h >= 0:
            chosen.add(h)
        used += extra
    out: list[str] = []
    for i in sorted(chosen):
        line = ENTRY_MARK.sub("", raw[i])
        if line.startswith("## ") and out:
            out.append("")
        out.append(line)
    return "\n".join(out).strip()
