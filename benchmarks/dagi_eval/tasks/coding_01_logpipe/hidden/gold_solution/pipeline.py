"""Gold solution: parse once, per-user single-pass sessionization, one-pass aggregates."""
import datetime
from pathlib import Path

SESSION_GAP_S = 1800
FUNNEL = ["view", "cart", "checkout", "purchase"]


def run(input_dir):
    by_user = {}
    day_users = {}
    for log_file in sorted(Path(input_dir, "logs").glob("*.log")):
        with open(log_file, encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                parts = line.split("|", 3)
                if len(parts) != 4 or not (parts[0] and parts[1] and parts[2]):
                    continue
                ts, user, event = parts[0], parts[1], parts[2]
                epoch = datetime.datetime.fromisoformat(ts).timestamp()
                by_user.setdefault(user, []).append((epoch, event))
                day_users.setdefault(ts[:10], set()).add(user)

    n_sessions = 0
    funnel = {s: 0 for s in FUNNEL}
    total_len = 0.0

    def close(start, end, stages):
        nonlocal n_sessions, total_len
        n_sessions += 1
        total_len += end - start
        for st in FUNNEL:
            if st in stages:
                funnel[st] += 1

    for user in by_user:
        evs = sorted(by_user[user])
        start = prev = evs[0][0]
        stages = {evs[0][1]}
        for epoch, event in evs[1:]:
            if epoch - prev <= SESSION_GAP_S:
                stages.add(event)
            else:
                close(start, prev, stages)
                start = epoch
                stages = {event}
            prev = epoch
        close(start, prev, stages)

    daily = {d: len(day_users[d]) for d in sorted(day_users)}
    avg = total_len / n_sessions if n_sessions else 0.0
    return {"sessions": n_sessions, "funnel": funnel,
            "avg_session_len_s": round(avg, 3), "daily_active": daily}
