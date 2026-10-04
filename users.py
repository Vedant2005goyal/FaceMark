"""Create students and faculty.

A person is a User row plus a Students or Faculty row (and, for students, their subject
enrolments). Each is written in one transaction, so a failure never leaves half a person behind.
Faces are added afterwards with register_faces.register_person().
"""


def create_student(db, name, email, roll_no, class_id, contact_no=None, parent_email=None, subject_ids=()):
    """Returns the new User_ID. Students must be enrolled in subjects to be marked Absent
    and to appear in attendance reports."""
    with db.transaction() as cursor:
        cursor.execute(
            "INSERT INTO User (Name, Email, Contact_No, User_Role) VALUES (%s, %s, %s, 'Student')",
            (name, email, contact_no))
        user_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO Students (User_ID, Roll_no, Parent_Email, Class_ID) VALUES (%s, %s, %s, %s)",
            (user_id, roll_no, parent_email, class_id))
        if subject_ids:
            cursor.executemany(
                "INSERT INTO Student_Subject (User_ID, Subject_ID) VALUES (%s, %s)",
                [(user_id, subject_id) for subject_id in subject_ids])
    return user_id


def create_faculty(db, name, email, department=None, faculty_role='Faculty', contact_no=None):
    """Returns the new User_ID."""
    with db.transaction() as cursor:
        cursor.execute(
            "INSERT INTO User (Name, Email, Contact_No, User_Role) VALUES (%s, %s, %s, 'Faculty')",
            (name, email, contact_no))
        user_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO Faculty (User_ID, Department, Faculty_Role) VALUES (%s, %s, %s)",
            (user_id, department, faculty_role))
    return user_id
