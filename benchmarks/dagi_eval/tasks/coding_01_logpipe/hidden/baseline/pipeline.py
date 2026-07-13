"""Log analytics pipeline: parse -> sessionize -> aggregate.

Contract (spec.md): run(input_dir) -> dict. Outputs must remain identical.
"""
import datetime
import re
from pathlib import Path

SESSION_GAP_S = 1800
FUNNEL = ["view", "cart", "checkout", "purchase"]


def _epoch(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").timestamp()


def parse_logs(input_dir):
    events = []
    for log_file in sorted(Path(input_dir, "logs").glob("*.log")):
        for line in log_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            pattern = re.compile(
                r"^(?P<ts>[^|]+)\|(?P<user>[^|]+)\|(?P<event>[^|]+)\|(?P<path>.*)$")
            m = pattern.match(line)
            if m is None:
                continue
            events.append({"ts": m.group("ts"), "user": m.group("user"),
                           "event": m.group("event"), "path": m.group("path")})
    return events


def sessionize(events):
    sessions = []
    for user in sorted({e["user"] for e in events}):
        mine = [e for e in events if e["user"] == user]
        mine = sorted(mine, key=lambda e: _epoch(e["ts"]))
        for e in mine:
            placed = False
            for s in sessions:
                if (s["user"] == user
                        and _epoch(e["ts"]) - _epoch(s["events"][-1]["ts"])
                        <= SESSION_GAP_S):
                    s["events"].append(e)
                    placed = True
                    break
            if not placed:
                sessions.append({"user": user, "events": [e]})
    return sessions


def aggregate(events, sessions):
    funnel = {}
    for stage in FUNNEL:
        count = 0
        for s in sessions:
            for e in s["events"]:
                if e["event"] == stage:
                    count += 1
                    break
        funnel[stage] = count
    daily = {}
    for day in sorted({e["ts"][:10] for e in events}):
        daily[day] = len({e["user"] for e in events if e["ts"][:10] == day})
    total = 0.0
    for s in sessions:
        total += _epoch(s["events"][-1]["ts"]) - _epoch(s["events"][0]["ts"])
    avg = total / len(sessions) if sessions else 0.0
    return {"sessions": len(sessions), "funnel": funnel,
            "avg_session_len_s": round(avg, 3), "daily_active": daily}


def run(input_dir):
    events = parse_logs(input_dir)
    sessions = sessionize(events)
    return aggregate(events, sessions)
