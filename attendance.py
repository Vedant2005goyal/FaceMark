"""Live attendance: recognise faces from the webcam and record Present / Late / Absent.

Flow: create_session() schedules a class -> MarkAttendance.recognize_user() runs the camera
loop for it -> close_session() marks everyone who never appeared as Absent and completes it.
Run directly for a demo on subject 1009.
"""
import json
from datetime import date, datetime, time, timedelta

import cv2 as cv
import face_recognition
import numpy as np

from config import Config
from database import DatabaseManager
from face_matching import ConfirmationTracker, FaceMatcher


def to_time(value):
    """MySQL TIME columns come back as timedelta; normalise to datetime.time."""
    if isinstance(value, timedelta):
        seconds = int(value.total_seconds())
        return time(seconds // 3600, (seconds % 3600) // 60, seconds % 60)
    return value


def compute_status(session_start, check_in: datetime, late_threshold_minutes: int) -> str:
    """'Late' if the check-in is more than the threshold after the session start, else 'Present'."""
    start = datetime.combine(check_in.date(), to_time(session_start))
    minutes_after_start = (check_in - start).total_seconds() / 60
    return 'Late' if minutes_after_start > late_threshold_minutes else 'Present'


def create_session(db, subject_id, session_date, start_time, end_time, created_by, session_type='Lecture'):
    """Faculty schedule a session ahead of time; returns its Session_ID."""
    return db.execute_query(
        """INSERT INTO Attendance_Session (Subject_ID, Session_Date, Start_Time, End_Time, Session_Type, Status, Created_By)
           VALUES (%s, %s, %s, %s, %s, 'Scheduled', %s)""",
        (subject_id, session_date, start_time, end_time, session_type, created_by))


def close_session(db, session_id) -> int:
    """Mark every enrolled student without an attendance row as Absent and set the session
    to Completed, in one transaction. Returns how many students were marked Absent."""
    absent_query = """
        INSERT INTO Attendance (Session_ID, User_ID, Subject_ID, Date, Status, Marked_By)
        SELECT s.Session_ID, ss.User_ID, s.Subject_ID, s.Session_Date, 'Absent', 'System'
        FROM Attendance_Session s
        JOIN Student_Subject ss ON ss.Subject_ID = s.Subject_ID
        WHERE s.Session_ID = %s
        AND NOT EXISTS (SELECT 1 FROM Attendance a
                        WHERE a.Session_ID = s.Session_ID AND a.User_ID = ss.User_ID)
    """
    with db.transaction() as cursor:
        cursor.execute(absent_query, (session_id,))
        absentees = cursor.rowcount
        cursor.execute("UPDATE Attendance_Session SET Status = 'Completed' WHERE Session_ID = %s", (session_id,))
    print(f"✓ Session {session_id} completed, {absentees} student(s) marked Absent")
    return absentees


class MarkAttendance:
    def __init__(self):
        self.db = DatabaseManager()
        self.matcher = FaceMatcher(tolerance=Config.FACE_RECOGNITION_TOLERANCE,
                                   strategy=Config.FACE_MATCH_STRATEGY)
        self.names = {}  # User_ID -> Name, for the on-screen labels
        self.load_known_faces()

    def load_known_faces(self):
        """Load every stored embedding into memory once, so matching never touches the DB."""
        rows = self.db.execute_query(
            "SELECT f.User_ID, u.Name, f.Face_Encoding FROM Face_Embeddings f JOIN User u ON f.User_ID = u.User_ID",
            fetch=True)
        for row in rows:
            self.matcher.add(row['User_ID'], np.array(json.loads(row['Face_Encoding'])))
            self.names[row['User_ID']] = row['Name']
        print(f"Loaded {len(rows)} photos of {len(self.matcher)} registered people")

    def get_setting(self, key, default):
        row = self.db.execute_query(
            "SELECT Setting_Value FROM Attendance_Settings WHERE Setting_Key = %s", (key,), fetch_one=True)
        return int(row['Setting_Value']) if row else default

    def get_active_session(self, subject_id):
        """Today's earliest session for the subject that hasn't been completed yet."""
        return self.db.execute_query(
            """SELECT Session_ID, Start_Time, End_Time, Session_Type FROM Attendance_Session
               WHERE Subject_ID = %s AND Session_Date = %s AND Status IN ('Scheduled', 'Ongoing')
               ORDER BY Start_Time LIMIT 1""",
            (subject_id, date.today()), fetch_one=True)

    def mark_attendance(self, user_id, session_id, subject_id) -> bool:
        already = self.db.execute_query(
            "SELECT 1 FROM Attendance WHERE User_ID = %s AND Session_ID = %s", (user_id, session_id), fetch_one=True)
        if already:
            return False
        session = self.db.execute_query(
            "SELECT Start_Time FROM Attendance_Session WHERE Session_ID = %s", (session_id,), fetch_one=True)
        now = datetime.now()
        late_threshold = self.get_setting('late_threshold_minutes', Config.LATE_THRESHOLD_MINUTES)
        status = compute_status(session['Start_Time'], now, late_threshold)
        try:
            self.db.execute_query(
                """INSERT INTO Attendance (Session_ID, User_ID, Subject_ID, Date, Check_In_Time, Status, Marked_By)
                   VALUES (%s, %s, %s, %s, %s, %s, 'Face Recognition')""",
                (session_id, user_id, subject_id, now.date(), now, status))
        except Exception as err:  # e.g. a recognised faculty member isn't in Students
            print(f"✗ Could not mark {self.names[user_id]}: {err}")
            return False
        print(f"✓ {self.names[user_id]} marked {status} at {now:%H:%M:%S}")
        return True

    def recognize_user(self, subject_id):
        """Run the webcam loop for the subject's active session. Press q to stop.
        Returns the Session_ID that was used, or None if there was no session."""
        session = self.get_active_session(subject_id)
        if not session:
            print(f"No active session today for subject {subject_id}; create one first")
            return None
        session_id = session['Session_ID']
        self.db.execute_query("UPDATE Attendance_Session SET Status = 'Ongoing' WHERE Session_ID = %s", (session_id,))
        print(f"Session {session_id} ({session['Start_Time']}-{session['End_Time']}). Press q to quit.")

        camera = cv.VideoCapture(0)
        tracker = ConfirmationTracker(required=Config.CONFIRM_FRAMES)
        scale = Config.FRAME_SCALE
        marked = set()
        faces = []  # (User_ID or None, box) from the last processed frame
        frame_count = 0

        while True:
            ok, frame = camera.read()
            if not ok:
                break

            # 1. Recognise on every Nth frame only; in between, redraw the last result
            if frame_count % Config.FRAME_SKIP == 0:
                small = cv.resize(frame, (0, 0), fx=scale, fy=scale)
                rgb = cv.cvtColor(small, cv.COLOR_BGR2RGB)  # OpenCV is BGR, dlib expects RGB
                boxes = face_recognition.face_locations(rgb, model=Config.FACE_DETECTION_MODEL)
                encodings = face_recognition.face_encodings(rgb, boxes)
                faces = [(self.matcher.match(enc)[0], box) for enc, box in zip(encodings, boxes)]

                # 2. Only mark someone after CONFIRM_FRAMES matches in a row
                for user_id in tracker.update(uid for uid, _ in faces if uid is not None):
                    if user_id not in marked:
                        self.mark_attendance(user_id, session_id, subject_id)
                        marked.add(user_id)
            frame_count += 1

            # 3. Draw boxes: red = unknown, yellow = confirming, orange = marked
            for user_id, box in faces:
                if user_id is None:
                    label, color = "Unknown", (0, 0, 255)
                elif user_id in marked:
                    label, color = f"{self.names[user_id]} - MARKED", (0, 165, 255)
                else:
                    label, color = f"{self.names[user_id]} (confirming)", (0, 255, 255)
                top, right, bottom, left = (int(v / scale) for v in box)
                cv.rectangle(frame, (left, top), (right, bottom), color, 2)
                cv.putText(frame, label, (left, bottom + 25), cv.FONT_HERSHEY_DUPLEX, 0.6, color, 1)
            cv.putText(frame, f"Session {session_id} | Marked: {len(marked)} | q to quit",
                       (10, 30), cv.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv.imshow('FaceMark', frame)
            if cv.waitKey(1) & 0xFF == ord('q'):
                break

        camera.release()
        cv.destroyAllWindows()
        return session_id


if __name__ == '__main__':
    system = MarkAttendance()
    now = datetime.now()
    create_session(
        system.db,
        subject_id=1009,  # Database Management Systems
        session_date=date.today(),
        start_time=now.time().replace(microsecond=0),
        end_time=(now + timedelta(hours=1)).time().replace(microsecond=0),
        created_by=16,  # the faculty member who teaches 1009
    )
    session_id = system.recognize_user(subject_id=1009)
    if session_id:
        close_session(system.db, session_id)
