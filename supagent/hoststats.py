"""(0.10.11.1) The servers Superset runs on, as the usage page shows them: every process of a Superset component (a web
server, a Celery worker, Celery beat) writes its host's CPU, load, memory, swap and disks, and what the Superset
processes of that host take, in supagent_meta (host:<host>:<role>) every SAMPLE_S seconds, with a day of history
(one point every HISTORY_S seconds). Read from /proc and os.statvfs: Linux, no package needed. A row not written for
GONE_S seconds is shown as gone (the host is down, or the component no longer runs there)."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import socket
import sys
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

SAMPLE_S = 60.0
HISTORY_S = 300.0
HISTORY_KEPT = 288             # a day of points, one every five minutes
GONE_S = 300.0
PREFIX = "host:"
_STARTED: dict[str, Any] = {}


def role_of(argv: list[str] | None = None) -> str | None:
    """web, worker or beat from this process's command line; None for a command (superset db upgrade, supagent CLI)."""
    words = " ".join(argv if argv is not None else sys.argv).lower()
    if "celery" in words:
        return "beat" if " beat" in words else "worker" if " worker" in words else None
    if any(w in words for w in ("gunicorn", "uwsgi", "waitress", "hypercorn", "uvicorn")):
        return "web"
    if (" run" in words and ("superset" in words or "flask" in words)) or "werkzeug" in words:
        return "web"
    return None


def _cpu_times() -> tuple[float, float] | None:
    try:
        with open("/proc/stat", encoding="ascii") as f:
            parts = f.readline().split()[1:]
        vals = [float(x) for x in parts[:8]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0.0)
        return sum(vals), idle
    except (OSError, ValueError, IndexError):
        return None


def _meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                k, _, v = line.partition(":")
                n = v.split()
                if n and n[0].isdigit():
                    out[k.strip()] = int(n[0]) * 1024
    except OSError:
        pass
    return out


def superset_places() -> list[tuple[str, str]]:
    """(0.11.0) (what, folder) of Superset on this host: its home (SUPERSET_HOME, else ~/.superset: the config, the
    uploads, the backups by default) and its installation (this Python's prefix: the venv)."""
    home = os.environ.get("SUPERSET_HOME") or os.path.join(os.path.expanduser("~"), ".superset")
    return [("Superset's home", home), ("its installation", sys.prefix)]


def _mounts() -> list[tuple[str, str, str]]:
    try:
        with open("/proc/mounts", encoding="ascii", errors="replace") as f:
            rows = [line.split()[:3] for line in f]
    except OSError:
        return [("-", "/", "-")]
    return [(dev, mount.replace("\\040", " "), fs) for dev, mount, fs in rows if len(mount) and mount.startswith("/")]


def _mount_of(path: str, mounts: list[tuple[str, str, str]]) -> str:
    """The mount point holding `path` (the longest one that contains it)."""
    p = os.path.realpath(path)
    best = "/"
    for _dev, mount, _fs in mounts:
        if (p == mount or p.startswith(mount.rstrip("/") + "/")) and len(mount) > len(best):
            best = mount
    return best


def _disks() -> list[dict[str, Any]]:
    """(0.11.0, the owner's request: "show only the size of the disk where superset is, /data for example") The disks
    holding Superset's home and its installation, each said with what it holds (one disk when both are on it)."""
    mounts = _mounts()
    out: list[dict[str, Any]] = []
    for what, path in superset_places():
        mount = _mount_of(path, mounts)
        same = next((d for d in out if d["mount"] == mount), None)
        if same is not None:
            same["holds"].append(what)
            continue
        try:
            st = os.statvfs(mount)
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        if total <= 0:
            continue
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        out.append({"mount": mount, "total": total, "used": used, "free": st.f_bavail * st.f_frsize,
                    "pct": round(100.0 * used / total, 1), "holds": [what], "path": path})
    return out


def _superset_processes() -> dict[str, Any]:
    """The processes of this host that run Superset (web, workers, beat): their count and resident memory."""
    n, rss = 0, 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").lower()
            if b"superset" not in cmd and b"supagent" not in cmd:
                continue
            with open(f"/proc/{pid}/status", encoding="ascii", errors="replace") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss += int(line.split()[1]) * 1024
                        break
            n += 1
        except (OSError, ValueError):
            continue
    return {"count": n, "rss": rss}


def sample(prev_cpu: tuple[float, float] | None = None) -> tuple[dict[str, Any], tuple[float, float] | None]:
    """This host now: CPU (since prev_cpu), load, memory, swap, disks, the Superset processes."""
    cpu = _cpu_times()
    pct = None
    if cpu and prev_cpu and cpu[0] > prev_cpu[0]:
        pct = round(100.0 * (1.0 - (cpu[1] - prev_cpu[1]) / (cpu[0] - prev_cpu[0])), 1)
    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        load = []
    mem = _meminfo()
    total, avail = mem.get("MemTotal", 0), mem.get("MemAvailable", mem.get("MemFree", 0))
    swap_t, swap_f = mem.get("SwapTotal", 0), mem.get("SwapFree", 0)
    return ({"at": dt.datetime.utcnow().isoformat(timespec="seconds"), "cpu_pct": pct, "cpus": os.cpu_count() or 0,
             "load": load, "mem_total": total, "mem_used": max(0, total - avail),
             "mem_pct": round(100.0 * (total - avail) / total, 1) if total else None,
             "swap_total": swap_t, "swap_used": max(0, swap_t - swap_f),
             "disks": _disks(), "superset": _superset_processes(), "pid": os.getpid()}, cpu)


def _key(host: str, role: str) -> str:
    return f"{PREFIX}{host[:52]}:{role}"[:64]


def _history(engine: Any, key: str) -> list[dict[str, Any]]:
    """The day of points a host's row keeps (written by this host's earlier process)."""
    from supagent import workers

    t = workers._meta()                                # one table object: its row only
    with engine.connect() as conn:
        row = conn.execute(t.select().where(t.c.key == key)).first()
    if row is None:
        return []
    return list((json.loads(row[1] or "{}") or {}).get("history") or [])[-HISTORY_KEPT:]


def _loop(app: Any, role: str) -> None:
    from supagent.workers import _engine, _write   # the heartbeat's own connection (no pool), as the workers do

    from supagent import workers

    workers._APP.setdefault("app", app)
    host = socket.gethostname()
    key = _key(host, role)
    history: list[dict[str, Any]] = []
    engine = None
    try:
        engine = _engine()
        history = _history(engine, key)                # the history kept by this host's earlier process, if any
    except Exception:  # pylint: disable=broad-except
        log.debug("supagent: host history not read", exc_info=True)
    prev = _cpu_times()
    time.sleep(5.0)
    while True:
        try:
            now, prev = sample(prev)
            last_at = history[-1]["at"] if history else ""
            if not last_at or (dt.datetime.fromisoformat(now["at"]) -
                               dt.datetime.fromisoformat(last_at)).total_seconds() >= HISTORY_S:
                history.append({"at": now["at"], "cpu": now["cpu_pct"], "mem": now["mem_pct"],
                                "load": (now["load"] or [None])[0],
                                "disk": max((d["pct"] for d in now["disks"]), default=None)})
                history = history[-HISTORY_KEPT:]
            engine = engine or _engine()
            _write(engine, key, json.dumps({"host": host, "role": role, "last": now, "history": history}))
        except Exception:  # pylint: disable=broad-except
            log.debug("supagent: host sample not written", exc_info=True)
        time.sleep(SAMPLE_S)


def start(app: Any, role: str | None = None) -> None:
    """Start this process's sampler (once per process and role; nothing for a command)."""
    role = role or role_of()
    if not role or sys.platform != "linux" or (role in _STARTED and _STARTED[role] == os.getpid()):
        return
    _STARTED[role] = os.getpid()
    threading.Thread(target=_loop, args=(app, role), name=f"supagent-host-{role}", daemon=True).start()


GONE_DAYS = 7                   # (0.11.0) a host's row not written for this long (a server retired) is removed


def purge_gone(days: int = GONE_DAYS) -> int:
    """(0.11.0) The rows of hosts gone for `days` removed (the hourly tick): the Servers card lists the others."""
    from superset.extensions import db

    from supagent.models import Meta

    limit = dt.datetime.utcnow() - dt.timedelta(days=days)
    gone = []
    for row in db.session.query(Meta).filter(Meta.key.like(f"{PREFIX}%")):
        try:
            at = dt.datetime.fromisoformat(str((json.loads(row.value or "{}").get("last") or {}).get("at") or ""))
        except (ValueError, TypeError):
            at = None
        if at is None or at < limit:
            gone.append(row.key)
    if gone:
        db.session.query(Meta).filter(Meta.key.in_(gone)).delete(synchronize_session=False)
        db.session.commit()
    return len(gone)


def hosts() -> list[dict[str, Any]]:
    """The hosts as the usage page shows them: per host its components (alive or gone) and its latest sample."""
    from superset.extensions import db

    from supagent.models import Meta

    now = dt.datetime.utcnow()
    by_host: dict[str, dict[str, Any]] = {}
    for m in db.session.query(Meta).filter(Meta.key.like(PREFIX + "%")).all():
        try:
            v = json.loads(m.value) if isinstance(m.value, str) else (m.value or {})
        except ValueError:
            continue
        last = v.get("last") or {}
        try:
            age = (now - dt.datetime.fromisoformat(last.get("at"))).total_seconds()
        except (TypeError, ValueError):
            continue
        h = by_host.setdefault(v.get("host") or "?", {"host": v.get("host") or "?", "roles": {}, "last": None,
                                                      "history": [], "age": None})
        h["roles"][v.get("role") or "?"] = {"alive": age <= GONE_S, "age": round(age)}
        if h["age"] is None or age < h["age"]:
            h.update(last=last, age=round(age), history=v.get("history") or [])
    return sorted(by_host.values(), key=lambda h: h["host"])
