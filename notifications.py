"""Attendance percentages and low-attendance emails to students, parents and faculty."""
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import Config
from database import DatabaseManager

# One row per student: how many completed sessions they have a row for, and how many of
# those were Present or Late. close_session() writes an Absent row for every no-show, so
# COUNT(*) is the number of sessions the student should have attended.
ATTENDANCE_QUERY = """
    SELECT u.User_ID AS user_id, u.Name AS name, u.Email AS email,
           st.Roll_no AS roll_no, st.Parent_Email AS parent_email,
           COUNT(*) AS total_sessions,
           SUM(a.Status IN ('Present', 'Late')) AS present_sessions
    FROM Attendance a
    JOIN Attendance_Session s ON s.Session_ID = a.Session_ID
    JOIN Students st ON st.User_ID = a.User_ID
    JOIN User u ON u.User_ID = a.User_ID
    WHERE s.Status = 'Completed' {filters}
    GROUP BY u.User_ID, u.Name, u.Email, st.Roll_no, st.Parent_Email
    ORDER BY u.Name
"""


class NotificationSystem:
    def __init__(self):
        self.db = DatabaseManager()

    def min_attendance_percentage(self) -> int:
        row = self.db.execute_query(
            "SELECT Setting_Value FROM Attendance_Settings WHERE Setting_Key = 'min_attendance_percentage'",
            fetch_one=True)
        return int(row['Setting_Value']) if row else Config.MIN_ATTENDANCE_PERCENTAGE

    def attendance_report(self, subject_id=None, user_id=None):
        """Attendance per student (optionally for one subject and/or one student) in a single query."""
        filters, params = '', []
        if subject_id:
            filters += ' AND a.Subject_ID = %s'
            params.append(subject_id)
        if user_id:
            filters += ' AND a.User_ID = %s'
            params.append(user_id)
        rows = self.db.execute_query(ATTENDANCE_QUERY.format(filters=filters), tuple(params), fetch=True)
        for row in rows:
            row['present_sessions'] = int(row['present_sessions'])
            row['absent_sessions'] = row['total_sessions'] - row['present_sessions']
            row['percentage'] = round(100 * row['present_sessions'] / row['total_sessions'], 2)
        return rows

    def get_low_attendance_students(self, subject_id=None):
        minimum = self.min_attendance_percentage()
        return [row for row in self.attendance_report(subject_id) if row['percentage'] < minimum]

    def subject_name(self, subject_id):
        if not subject_id:
            return None
        row = self.db.execute_query("SELECT Subject_Name FROM Subject WHERE Subject_ID = %s", (subject_id,), fetch_one=True)
        return row['Subject_Name'] if row else None

    # ---- email ----

    def send_email(self, to_email, subject, html) -> bool:
        msg = MIMEMultipart('alternative')
        msg['From'] = Config.SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html, 'html'))
        try:
            # Port 465 is TLS from the start; 587 (the default) upgrades a plain connection with STARTTLS
            if Config.SMTP_PORT == 465:
                server = smtplib.SMTP_SSL(Config.SMTP_SERVER, Config.SMTP_PORT)
            else:
                server = smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT)
                server.starttls()
            server.login(Config.SENDER_EMAIL, Config.SENDER_PASSWORD)
            server.send_message(msg)
            server.quit()
            print(f"✓ Email sent to {to_email}")
            return True
        except Exception as e:
            print(f"✗ Failed to send email to {to_email}: {e}")
            return False

    def email_html(self, title, body):
        return f"""<html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
            <h2 style="color: #d9534f;">{title}</h2>
            {body}
            <p style="color: #666; font-size: 12px;">Automated message from FaceMark, {datetime.now():%d %b %Y %H:%M}</p>
            </body></html>"""

    def summary_html(self, student):
        return f"""<ul>
            <li>Attendance: <b>{student['percentage']}%</b> (required: {self.min_attendance_percentage()}%)</li>
            <li>Attended: {student['present_sessions']} of {student['total_sessions']} sessions</li>
            <li>Missed: {student['absent_sessions']}</li></ul>"""

    def notify_student(self, user_id, subject_id=None) -> bool:
        report = self.attendance_report(subject_id, user_id)
        if not report:
            print(f"✗ No completed sessions for student {user_id}")
            return False
        student, name = report[0], self.subject_name(subject_id)
        where = f" in {name}" if name else ""
        body = (f"<p>Dear {student['name']},</p><p>Your attendance{where} is below the required minimum.</p>"
                f"{self.summary_html(student)}<p>Please attend the upcoming classes.</p>")
        return self.send_email(student['email'], f"Low Attendance Alert{where}",
                               self.email_html("Low Attendance Alert", body))

    def notify_parent(self, user_id, subject_id=None) -> bool:
        report = self.attendance_report(subject_id, user_id)
        if not report or not report[0]['parent_email']:
            print(f"✗ No parent email or attendance data for student {user_id}")
            return False
        student, name = report[0], self.subject_name(subject_id)
        where = f" in {name}" if name else ""
        body = (f"<p>Dear Parent/Guardian,</p><p>Your ward <b>{student['name']}</b> has low attendance{where}.</p>"
                f"{self.summary_html(student)}")
        return self.send_email(student['parent_email'], f"Your Ward's Attendance Alert{where}",
                               self.email_html("Student Attendance Alert", body))

    def notify_teacher(self, faculty_id, subject_id=None) -> bool:
        teacher = self.db.execute_query("SELECT Name, Email FROM User WHERE User_ID = %s", (faculty_id,), fetch_one=True)
        low = self.get_low_attendance_students(subject_id)
        if not teacher or not low:
            return False
        name = self.subject_name(subject_id)
        rows = ''.join(f"<tr><td>{s['name']}</td><td>{s['roll_no']}</td><td>{s['percentage']}%</td>"
                       f"<td>{s['present_sessions']}/{s['total_sessions']}</td></tr>" for s in low)
        body = (f"<p>Dear {teacher['Name']},</p><p>{len(low)} student(s) are below the minimum attendance"
                f"{' for ' + name if name else ''}:</p>"
                f"<table border='1' cellpadding='6' style='border-collapse: collapse;'>"
                f"<tr><th>Student</th><th>Roll No</th><th>Attendance</th><th>Present/Total</th></tr>{rows}</table>")
        return self.send_email(teacher['Email'], f"Low Attendance Report{' - ' + name if name else ''}",
                               self.email_html("Low Attendance Report", body))

    def bulk_notify_low_attendance(self, subject_id=None, notify_parents=False):
        stats = {'total_students': 0, 'students_notified': 0, 'parents_notified': 0, 'failed': 0}
        for student in self.get_low_attendance_students(subject_id):
            stats['total_students'] += 1
            if self.notify_student(student['user_id'], subject_id):
                stats['students_notified'] += 1
            else:
                stats['failed'] += 1
            if notify_parents and self.notify_parent(student['user_id'], subject_id):
                stats['parents_notified'] += 1
        print(f"Notifications: {stats}")
        return stats


if __name__ == "__main__":
    for s in NotificationSystem().get_low_attendance_students(subject_id=1009):
        print(f"{s['name']:<20} {s['percentage']}%  ({s['present_sessions']}/{s['total_sessions']})")
