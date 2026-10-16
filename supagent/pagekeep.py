"""(0.10.11.1) What an answer keeps for the chat page, bounded. A query's rows were kept whole (5000 rows of 6
queries, every cell as long as the database gave it): raw log lines with their stack traces made one answer tens of
megabytes, that the server read and sent again at every opening of the chat and the browser parsed and drew, in the
same thread as the Superset page around the chat panel. Here: at most RESULT_COLUMNS columns, CELL_CHARS per cell
and a byte budget per answer (the first rows kept, the result marked cut: the Excel extract gives every row; the
query itself is kept whole). Answers kept before 0.10.11.1 are cut when they are next read. The steps are kept whole
(0.10.11.2: Helpful keeps a step's SQL as an example, the learning reads their queries): fit_steps cuts the copy
sent to the page only."""
from __future__ import annotations

import json
from typing import Any

CELL_CHARS = 2000             # one cell's text (a log line, a stack trace, a document) at most
RESULT_COLUMNS = 120
RESULTS_BYTES = 3_000_000     # the rows of all the results of one answer at most (JSON)
RESULT_BYTES = 1_500_000      # one result's rows at most, when it is alone
FIT = "fit"                   # set on a result once bounded: read again as it is
ARGS_CHARS = 4000             # a step's arguments as the page shows them
STEP_LIST = 40                # a step's found / read items
TEXT_CHARS = 1000             # a string inside a step's arguments or items


def _dumps(v: Any) -> str:
    return json.dumps(v, default=str, ensure_ascii=False)


def _cell(v: Any) -> Any:
    if isinstance(v, str):
        return v if len(v) <= CELL_CHARS else v[:CELL_CHARS] + " …"
    if isinstance(v, (dict, list, tuple)):
        s = _dumps(v)
        return v if len(s) <= CELL_CHARS else s[:CELL_CHARS] + " …"
    return v


def fit_result(item: dict, budget: int = RESULT_BYTES) -> dict:
    """One result as the page keeps it (the first rows that fit `budget`); row_count stays the query's own."""
    cols = list(item.get("columns") or [])
    cut = len(cols) > RESULT_COLUMNS            # values cut (columns, long cells)
    cols = cols[:RESULT_COLUMNS]
    kept: list = []
    size, dropped = 2, False                    # rows left out
    for r in item.get("rows") or []:
        if isinstance(r, (list, tuple)):
            new = [_cell(v) for v in list(r)[:len(cols)]]
            cut = cut or len(r) > len(cols) or any(a is not b for a, b in zip(new, r))
        else:
            new = _cell(r)
            cut = cut or new is not r
        n = len(_dumps(new)) + 1
        if kept and size + n > budget:
            dropped = True
            break
        kept.append(new)
        size += n
    out = dict(item, columns=cols, rows=kept)
    out[FIT] = 1
    if dropped:
        out["truncated"] = True                 # the page says "first N rows here" (an Excel extract has them all)
    if cut or dropped:
        out["cut_for_page"] = True              # and that long values were cut
    return out


def fit_results(results: list | None) -> tuple[list, bool]:
    """(the results bounded, whether they changed): results already bounded are given back as they are."""
    results = list(results or [])
    if all(isinstance(r, dict) and r.get(FIT) for r in results):
        return results, False
    each = min(RESULT_BYTES, RESULTS_BYTES // max(1, len(results)))
    return [fit_result(r, each) if isinstance(r, dict) else r for r in results], True


def _short(v: Any, depth: int = 0) -> Any:
    if isinstance(v, str):
        return v if len(v) <= TEXT_CHARS else v[:TEXT_CHARS] + " …"
    if depth > 6:
        return _short(_dumps(v))
    if isinstance(v, dict):
        return {k: _short(x, depth + 1) for k, x in list(v.items())[:60]}
    if isinstance(v, (list, tuple)):
        return [_short(x, depth + 1) for x in list(v)[:STEP_LIST]]
    return v


def fit_steps(steps: list | None) -> list:
    """The steps as the page keeps them: arguments, found and read items cut (the result head is cut already)."""
    out = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        s = dict(s)
        args = s.get("args")
        if args is not None and len(_dumps(args)) > ARGS_CHARS:
            args = _short(args)
            if len(_dumps(args)) > ARGS_CHARS:
                args = {"(cut)": _dumps(args)[:ARGS_CHARS] + " …"}
            s["args"] = args
        for key in ("found", "read"):
            if isinstance(s.get(key), list) and len(_dumps(s[key])) > ARGS_CHARS:
                s[key] = _short(s[key])
        if isinstance(s.get("ledger"), dict) and len(_dumps(s["ledger"])) > 4 * ARGS_CHARS:
            s["ledger"] = _short(s["ledger"])
        if isinstance(s.get("result"), str) and len(s["result"]) > 1500:
            s["result"] = s["result"][:1500]
        out.append(s)
    return out
