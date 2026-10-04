"""REST API for managing sessions, registering faces and sending attendance alerts.

Run with `python api.py` (or `uvicorn api:app --port 5050`); interactive docs at /docs.
The webcam loop itself runs locally (attendance.py) because it needs a camera and a screen.

Endpoints are plain `def`, not `async def`: the MySQL driver and dlib are blocking, so
FastAPI runs each request in its threadpool and every request borrows its own pooled connection.
"""
from datetime import date, datetime, time
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mysql.connector.errors import IntegrityError
from pydantic import BaseModel, Field

from attendance import close_session, create_session
from config import Config
from database import DatabaseManager
from notifications import NotificationSystem
from register_faces import FaceRegistration, RegistrationError
from users import create_faculty, create_student

app = FastAPI(title="FaceMark")
db = DatabaseManager()
registration = FaceRegistration()
notifications = NotificationSystem()


class NewStudentRequest(BaseModel):
    name: str = Field(max_length=100)
    email: str = Field(max_length=100)
    roll_no: str = Field(max_length=9)
    class_id: int
    contact_no: Optional[str] = Field(None, max_length=10)
    parent_email: Optional[str] = Field(None, max_length=100)
    subject_ids: List[int] = []


class NewFacultyRequest(BaseModel):
    name: str = Field(max_length=100)
    email: str = Field(max_length=100)
    department: Optional[str] = Field(None, max_length=50)
    faculty_role: str = Field('Faculty', max_length=20)
    contact_no: Optional[str] = Field(None, max_length=10)


class RegisterFaceRequest(BaseModel):
    user_id: int
    image_path: str  # the image must already be on the server


class NewSessionRequest(BaseModel):
    subject_id: int
    session_date: date
    start_time: time
    end_time: time
    created_by: int
    session_type: str = 'Lecture'


class NotifyRequest(BaseModel):
    user_id: int
    subject_id: Optional[int] = None


class BulkNotifyRequest(BaseModel):
    subject_id: Optional[int] = None
    notify_parents: bool = False


@app.exception_handler(RegistrationError)
def handle_registration_error(request: Request, e: RegistrationError):
    """File not found / no face (400), unknown user (404), duplicate photo or 5-photo cap (409)."""
    return JSONResponse(status_code=e.status, content={'success': False, 'error': str(e)})


@app.exception_handler(IntegrityError)
def handle_integrity_error(request: Request, e: IntegrityError):
    """A UNIQUE clash (duplicate email or roll no) is a 409; a missing referenced row
    (unknown class or subject id) is the client's mistake, so 400."""
    status = 409 if e.errno == 1062 else 400
    return JSONResponse(status_code=status, content={'success': False, 'error': e.msg})


@app.exception_handler(Exception)
def handle_error(request: Request, e: Exception):
    """Unexpected errors (e.g. a database error) come back as JSON instead of a bare 500."""
    return JSONResponse(status_code=500, content={'success': False, 'error': str(e)})


@app.get('/health')
def health():
    return {'status': 'healthiest', 'timestamp': datetime.now().isoformat()}


@app.post('/api/students', status_code=201)
def new_student(body: NewStudentRequest):
    user_id = create_student(db, body.name, body.email, body.roll_no, body.class_id,
                             body.contact_no, body.parent_email, body.subject_ids)
    return {'success': True, 'user_id': user_id}


@app.post('/api/faculty', status_code=201)
def new_faculty(body: NewFacultyRequest):
    user_id = create_faculty(db, body.name, body.email, body.department, body.faculty_role, body.contact_no)
    return {'success': True, 'user_id': user_id}


@app.post('/api/register-face')
def register_face(body: RegisterFaceRequest):
    return {'success': True, 'photos': registration.register_person(body.user_id, body.image_path)}


@app.post('/api/sessions')
def new_session(body: NewSessionRequest):
    session_id = create_session(db, body.subject_id, body.session_date, body.start_time,
                                body.end_time, body.created_by, body.session_type)
    return {'success': True, 'session_id': session_id}


@app.post('/api/sessions/{session_id}/close')
def end_session(session_id: int):
    """Mark no-shows Absent and complete the session."""
    return {'success': True, 'absent_marked': close_session(db, session_id)}


@app.get('/api/attendance/low')
def low_attendance(subject_id: Optional[int] = None):
    students = notifications.get_low_attendance_students(subject_id)
    return {'success': True, 'count': len(students), 'students': students}


@app.post('/api/notify/student')
def notify_student(body: NotifyRequest):
    return {'success': notifications.notify_student(body.user_id, body.subject_id)}


@app.post('/api/notify/parent')
def notify_parent(body: NotifyRequest):
    return {'success': notifications.notify_parent(body.user_id, body.subject_id)}


@app.post('/api/notify/bulk')
def notify_bulk(body: BulkNotifyRequest = BulkNotifyRequest()):
    stats = notifications.bulk_notify_low_attendance(body.subject_id, body.notify_parents)
    return {'success': True, 'stats': stats}


if __name__ == '__main__':
    Config.validate()
    uvicorn.run(app, host='0.0.0.0', port=Config.API_PORT)
