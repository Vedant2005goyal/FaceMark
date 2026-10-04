from contextlib import contextmanager
from datetime import datetime, time, timedelta

from attendance import close_session, compute_status, to_time


def test_to_time_converts_mysql_timedelta():
    assert to_time(timedelta(hours=15, minutes=40, seconds=5)) == time(15, 40, 5)
    assert to_time(time(9, 0)) == time(9, 0)


def test_on_time_is_present():
    assert compute_status(time(9, 0), datetime(2026, 1, 5, 9, 5), 10) == 'Present'


def test_exactly_at_threshold_is_present():
    assert compute_status(time(9, 0), datetime(2026, 1, 5, 9, 10), 10) == 'Present'


def test_after_threshold_is_late():
    assert compute_status(timedelta(hours=9), datetime(2026, 1, 5, 9, 11), 10) == 'Late'


def test_early_arrival_is_present():
    assert compute_status(time(9, 0), datetime(2026, 1, 5, 8, 55), 10) == 'Present'


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.rowcount = 0

    def execute(self, sql, params):
        self.statements.append((' '.join(sql.split()), params))
        if sql.strip().startswith('INSERT'):
            self.rowcount = 4


class FakeDB:
    def __init__(self):
        self.cursor = FakeCursor()

    @contextmanager
    def transaction(self):
        yield self.cursor


def test_close_session_marks_absent_then_completes():
    db = FakeDB()
    assert close_session(db, 42) == 4
    (insert, p1), (update, p2) = db.cursor.statements
    assert insert.startswith('INSERT INTO Attendance') and "'Absent'" in insert and 'NOT EXISTS' in insert
    assert update.startswith('UPDATE Attendance_Session') and "'Completed'" in update
    assert p1 == p2 == (42,)
