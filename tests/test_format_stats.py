import os
from datetime import datetime

os.environ.setdefault("API_TOKEN", "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")
os.environ.setdefault("DATABASE_URL", "postgresql://test")

from main import format_stats_message


def _sample_stats():
    return {
        "Project A": [
            {"start_time": datetime(2026, 6, 12, 10, 0), "seconds": 4800, "comment": "task 1"},
            {"start_time": datetime(2026, 6, 12, 14, 0), "seconds": 6600, "comment": "task 2"},
            {"start_time": datetime(2026, 6, 11, 9, 0), "seconds": 3600, "comment": "task 3"},
        ],
        "Project B": [
            {"start_time": datetime(2026, 6, 12, 11, 0), "seconds": 7260, "comment": "dev"},
            {"start_time": datetime(2026, 6, 8, 9, 0), "seconds": 3600, "comment": "planning"},
        ],
    }


def test_period_total_on_same_line_as_total_label():
    message = format_stats_message(_sample_stats(), "for the week")
    lines = message.splitlines()

    assert lines[2] == "Total: ⏱ 07:11"
    assert lines[3] == "Project A | 3 — 04:10"
    assert lines[4] == "Project B | 2 — 03:01"


def test_day_total_on_same_line_as_date_header():
    message = format_stats_message(_sample_stats(), "for the week")
    lines = message.splitlines()

    day_header_idx = lines.index("## 12.06.2026 — ⏱ 05:11")
    assert lines[day_header_idx + 2].startswith("Project A (sessions: 2")


def test_empty_stats():
    assert format_stats_message({}, "for the week") == (
        "📊 Statistics for the week\n\nNo data yet."
    )
