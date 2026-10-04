"""Background jobs: close finished sessions every 5 minutes, and (optionally) email
low-attendance alerts once a day."""
import time

import schedule

from attendance import close_session
from config import Config
from database import DatabaseManager
from notifications import NotificationSystem


def close_finished_sessions():
    """Complete every session whose end time has passed, marking no-shows Absent."""
    db = DatabaseManager()
    finished = db.execute_query(
        """SELECT Session_ID FROM Attendance_Session
           WHERE Status IN ('Scheduled', 'Ongoing') AND TIMESTAMP(Session_Date, End_Time) < NOW()""",
        fetch=True)
    for row in finished:
        try:
            close_session(db, row['Session_ID'])
        except Exception as e:
            print(f"✗ Could not close session {row['Session_ID']}: {e}")


def daily_low_attendance_emails():
    """For each active subject: email every student below the minimum, then their teacher."""
    notifications = NotificationSystem()
    subjects = DatabaseManager().execute_query(
        "SELECT Subject_ID, User_ID FROM Subject WHERE Is_Active = TRUE", fetch=True)
    for subject in subjects:
        low = notifications.get_low_attendance_students(subject['Subject_ID'])
        for student in low:
            notifications.notify_student(student['user_id'], subject['Subject_ID'])
        if low and subject['User_ID']:
            notifications.notify_teacher(subject['User_ID'], subject['Subject_ID'])


if __name__ == '__main__':
    schedule.every(5).minutes.do(close_finished_sessions)
    if Config.AUTO_NOTIFY_ENABLED:
        schedule.every().day.at(Config.AUTO_NOTIFY_SCHEDULE).do(daily_low_attendance_emails)
        print(f"Daily alerts scheduled at {Config.AUTO_NOTIFY_SCHEDULE}")
    print("Scheduler running (closes finished sessions every 5 minutes)")
    while True:
        schedule.run_pending()
        time.sleep(30)
