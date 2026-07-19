"""Log analytics pipeline: parse -> sessionize -> aggregate.

Contract (spec.md): run(input_dir) -> dict. Outputs must remain identical.
"""
import datetime
from pathlib import Path

SESSION_GAP_S = 1800
FUNNEL = ["view", "cart", "checkout", "purchase"]


def _make_epoch_fn():
    """Return a memoized ts-string -> epoch-seconds converter (per-run cache)."""
    cache = {}

    def epoch(ts):
        v = cache.get(ts)
        if v is None:
            v = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").timestamp()
            cache[ts] = v
        return v

    return epoch


def parse_logs(input_dir):
    events = []
    for log_file in sorted(Path(input_dir, "logs").glob("*.log")):
        for line in log_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parts = line.split("|", 3)
            if len(parts) != 4:
                continue
            ts, user, event, path = parts
            if not ts or not user or not event:
                continue
            events.append({"ts": ts, "user": user, "event": event, "path": path})
    return events


def sessionize(events, epoch):
    by_user = {}
    for e in events:
        by_user.setdefault(e["user"], []).append(e)

    sessions = []
    for user in sorted(by_user):
        mine = sorted(by_user[user], key=lambda e: epoch(e["ts"]))
        cur = None
        for e in mine:
            t = epoch(e["ts"])
            if cur is not None and t - cur["last_t"] <= SESSION_GAP_S:
                cur["events"].append(e)
                cur["last_t"] = t
            else:
                cur = {"user": user, "events": [e], "last_t": t}
                sessions.append(cur)
    return sessions


def aggregate(events, sessions, epoch):
    funnel = {stage: 0 for stage in FUNNEL}
    total = 0.0
    for s in sessions:
        ev = s["events"]
        stages = {e["event"] for e in ev}
        for stage in FUNNEL:
            if stage in stages:
                funnel[stage] += 1
        total += epoch(ev[-1]["ts"]) - epoch(ev[0]["ts"])
    avg = total / len(sessions) if sessions else 0.0

    daily_users = {}
    for e in events:
        day = e["ts"][:10]
        s = daily_users.get(day)
        if s is None:
            daily_users[day] = s = set()
        s.add(e["user"])
    daily = {day: len(daily_users[day]) for day in sorted(daily_users)}

    return {"sessions": len(sessions), "funnel": funnel,
            "avg_session_len_s": round(avg, 3), "daily_active": daily}


def run(input_dir):
    events = parse_logs(input_dir)
    epoch = _make_epoch_fn()
    sessions = sessionize(events, epoch)
    return aggregate(events, sessions, epoch)
