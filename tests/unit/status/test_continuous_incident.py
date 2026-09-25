"""Mathematical verification of continuous incident duration and hourly buckets aggregation."""

from datetime import datetime, timezone

THRESHOLD_MINOR = 300  # 5 minutes
THRESHOLD_MAJOR = 1200  # 20 minutes


def overlap_seconds(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> float:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return max(0.0, (end - start).total_seconds())


def get_continuous_down_intervals(
    flips: list[dict], window_start: datetime, now: datetime, initial_up: bool
):
    intervals = []
    down_since = None if initial_up else window_start

    for flip in flips:
        t = flip["timestamp"]
        if t <= window_start:
            if flip["up"] == 0:
                down_since = t
            else:
                down_since = None
            continue
        if t > now:
            break

        if flip["up"] == 0:
            if not down_since:
                down_since = t
        else:
            if down_since:
                intervals.append({"start": down_since, "end": t})
                down_since = None

    if down_since:
        intervals.append({"start": down_since, "end": now})

    return intervals


def calculate_hour_buckets(
    intervals: list[dict], first_hour_start: datetime, now: datetime, window_hours: int = 24
):
    interval_states = []
    for inv in intervals:
        dur = max(0.0, (inv["end"] - inv["start"]).total_seconds())
        interval_states.append(
            {
                "start": inv["start"],
                "end": inv["end"],
                "duration": dur,
                "is_major": dur >= THRESHOLD_MAJOR,
                "is_minor": dur >= THRESHOLD_MINOR,
            }
        )

    hours = []
    for i in range(window_hours):
        h_start = datetime.fromtimestamp(first_hour_start.timestamp() + i * 3600, tz=timezone.utc)
        h_end = datetime.fromtimestamp(h_start.timestamp() + 3600, tz=timezone.utc)
        actual_start = max(h_start, first_hour_start)
        actual_end = min(h_end, now)

        if actual_end <= actual_start:
            hours.append({"date": h_start.isoformat(), "state": "nodata", "down": 0})
            continue

        down = 0.0
        has_major = False
        has_minor = False

        for inv in interval_states:
            overlap = overlap_seconds(actual_start, actual_end, inv["start"], inv["end"])
            down += overlap
            if overlap > 0:
                if inv["is_major"]:
                    has_major = True
                elif inv["is_minor"]:
                    has_minor = True

        state = "ok"
        if has_major or down >= THRESHOLD_MAJOR:
            state = "down"
        elif has_minor or down >= THRESHOLD_MINOR:
            state = "minor"

        hours.append({"date": h_start.isoformat(), "state": state, "down": down})

    return hours


def test_incident_00_50_progression():
    """Verifies the exact scenario described in the requirements:
    Incident starts at 00:50:
    - At 00:54 (4 min down): bucket 00:00-01:00 is OK (green).
    - At 00:55 (5 min down): bucket 00:00-01:00 turns MINOR (orange).
    - At 01:00 (10 min down): bucket 00:00-01:00 is MINOR (orange).
    - At 01:05 (15 min down): bucket 00:00-01:00 is MINOR, bucket 01:00-02:00 is MINOR.
    - At 01:10 (20 min down continuous): BOTH buckets turn DOWN (red) without resetting!
    """
    first_hour = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)
    t_start = datetime(2026, 9, 10, 0, 50, tzinfo=timezone.utc)
    flips = [{"timestamp": t_start, "up": 0}]

    # 1. At 00:54 (4 minutes down)
    now_00_54 = datetime(2026, 9, 10, 0, 54, tzinfo=timezone.utc)
    inv_54 = get_continuous_down_intervals(flips, first_hour, now_00_54, initial_up=True)
    buckets_54 = calculate_hour_buckets(inv_54, first_hour, now_00_54, window_hours=2)
    assert buckets_54[0]["state"] == "ok"
    assert buckets_54[0]["down"] == 240.0

    # 2. At 00:55 (5 minutes down)
    now_00_55 = datetime(2026, 9, 10, 0, 55, tzinfo=timezone.utc)
    inv_55 = get_continuous_down_intervals(flips, first_hour, now_00_55, initial_up=True)
    buckets_55 = calculate_hour_buckets(inv_55, first_hour, now_00_55, window_hours=2)
    assert buckets_55[0]["state"] == "minor"
    assert buckets_55[0]["down"] == 300.0

    # 3. At 01:05 (15 minutes continuous down, crossed hour boundary)
    now_01_05 = datetime(2026, 9, 10, 1, 5, tzinfo=timezone.utc)
    inv_05 = get_continuous_down_intervals(flips, first_hour, now_01_05, initial_up=True)
    buckets_05 = calculate_hour_buckets(inv_05, first_hour, now_01_05, window_hours=2)
    assert buckets_05[0]["state"] == "minor"
    assert buckets_05[0]["down"] == 600.0
    assert buckets_05[1]["state"] == "minor"
    assert buckets_05[1]["down"] == 300.0

    # 4. At 01:10 (20 minutes continuous down)
    now_01_10 = datetime(2026, 9, 10, 1, 10, tzinfo=timezone.utc)
    inv_10 = get_continuous_down_intervals(flips, first_hour, now_01_10, initial_up=True)
    buckets_10 = calculate_hour_buckets(inv_10, first_hour, now_01_10, window_hours=2)
    # Both closed and open hours turn DOWN (red) to prevent understating incident severity
    assert buckets_10[0]["state"] == "down"
    assert buckets_10[0]["down"] == 600.0
    assert buckets_10[1]["state"] == "down"
    assert buckets_10[1]["down"] == 600.0


def test_resolved_minor_incident_does_not_turn_down():
    """If an incident starts at 00:50 and resolves at 01:05 (15 min total):
    It was minor throughout. Neither bucket should turn down (red).
    """
    first_hour = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)
    flips = [
        {"timestamp": datetime(2026, 9, 10, 0, 50, tzinfo=timezone.utc), "up": 0},
        {"timestamp": datetime(2026, 9, 10, 1, 5, tzinfo=timezone.utc), "up": 1},
    ]
    now = datetime(2026, 9, 10, 1, 30, tzinfo=timezone.utc)
    inv = get_continuous_down_intervals(flips, first_hour, now, initial_up=True)
    buckets = calculate_hour_buckets(inv, first_hour, now, window_hours=2)

    assert buckets[0]["state"] == "minor"
    assert buckets[1]["state"] == "minor"
