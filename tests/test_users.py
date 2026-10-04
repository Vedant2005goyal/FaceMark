from contextlib import contextmanager

from users import create_faculty, create_student


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.lastrowid = 25

    def execute(self, sql, params):
        self.statements.append((sql.split(' (')[0], params))

    def executemany(self, sql, rows):
        self.statements.append((sql.split(' (')[0], rows))


class FakeDB:
    def __init__(self):
        self.cursor = FakeCursor()

    @contextmanager
    def transaction(self):
        yield self.cursor


def test_create_student_writes_user_student_and_enrolments():
    db = FakeDB()
    assert create_student(db, 'Priya', 'p@x.edu', '10230999', 105, subject_ids=[1009, 1010]) == 25
    tables = [table for table, _ in db.cursor.statements]
    assert tables == ['INSERT INTO User', 'INSERT INTO Students', 'INSERT INTO Student_Subject']
    assert db.cursor.statements[1][1] == (25, '10230999', None, 105)
    assert db.cursor.statements[2][1] == [(25, 1009), (25, 1010)]


def test_create_student_without_subjects_skips_enrolment():
    db = FakeDB()
    create_student(db, 'Priya', 'p@x.edu', '10230999', 105)
    assert [table for table, _ in db.cursor.statements] == ['INSERT INTO User', 'INSERT INTO Students']


def test_create_faculty_writes_user_and_faculty():
    db = FakeDB()
    assert create_faculty(db, 'Dr. Rao', 'rao@x.edu', department='COE', faculty_role='Professor') == 25
    assert [table for table, _ in db.cursor.statements] == ['INSERT INTO User', 'INSERT INTO Faculty']
    assert db.cursor.statements[1][1] == (25, 'COE', 'Professor')
