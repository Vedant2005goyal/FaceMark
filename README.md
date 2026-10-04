# FaceMark

Face-recognition attendance system. A webcam recognizes enrolled students during a class session and records them as Present or Late. Students who never appear are marked Absent when the session closes, and anyone below the minimum attendance (75%) gets an email alert, as do their parents and teacher.

**Stack:** Python, OpenCV, dlib (via `face_recognition`), NumPy, MySQL, FastAPI, Docker

## Results

Measured with the scripts in [`benchmarks/`](benchmarks/README.md) on an Apple M1 CPU:

| | |
|---|---|
| Rank-1 identification accuracy (LFW, 119 enrolled identities) | **99.1%** |
| Strangers wrongly accepted, after threshold tuning (was 10.9%) | **0.97%** |
| Equal error rate, 5-photo enrollment vs 1 photo | **3.1%** (was 8.8%) |
| Live pipeline speed (720p, 4× downscale) | **46 ms/frame, ~22 FPS** |
| DB query latency, connection pool vs new connection | **~5× lower** |

## How it works

```
register_faces.py      photo ──► detect face ──► 128-d embedding ──► Face_Embeddings (MySQL)

attendance.py          webcam frame ──► downscale ¼ ──► detect + embed ──► nearest enrolled student
                       (every 2nd frame)                               │
                                                     same match 3 frames in a row?
                                                                       ▼
                                                 Attendance row: Present / Late

close_session()        session over ──► enrolled students with no row ──► Absent; session Completed

notifications.py       attendance % per student (one SQL query) ──► email if below 75%
scheduler.py           closes finished sessions every 5 min, sends daily alerts
users.py, api.py       REST endpoints for students/faculty, sessions, registration, reports, alerts
```

`face_matching.py` holds the detection, encoding and matching logic. The app and the benchmarks both use it, so the measured numbers describe the real code.

## Setup

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt   # dlib needs cmake
cp .env.example .env                                                     # fill in DB + email credentials

mysql -u root -p -e "CREATE DATABASE attendance_system"
mysql -u root -p attendance_system < schema.sql

.venv/bin/python register_faces.py   # enroll sample_faces/<Name>/*.jpg
.venv/bin/python attendance.py       # demo: open the webcam for subject 1009 (q to quit)
.venv/bin/python api.py              # REST API on API_PORT
.venv/bin/pytest                     # unit tests
```

Or run MySQL, the API and the scheduler with `docker-compose up` (API on port 5050). The webcam loop runs on the host.

## API

FastAPI, with interactive docs at `/docs`. Request bodies are validated by Pydantic models, so a missing or mistyped field returns 422 with the field named.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/api/students` | `{name, email, roll_no, class_id, contact_no?, parent_email?, subject_ids?}`: create a student and enroll them in subjects |
| POST | `/api/faculty` | `{name, email, department?, faculty_role?, contact_no?}`: create a faculty member |
| POST | `/api/register-face` | `{user_id, image_path}`: enroll a photo |
| POST | `/api/sessions` | `{subject_id, session_date, start_time, end_time, created_by}`: schedule a class |
| POST | `/api/sessions/<id>/close` | Mark no-shows Absent, complete the session |
| GET | `/api/attendance/low?subject_id=` | Students below the minimum |
| POST | `/api/notify/student`, `/api/notify/parent` | `{user_id, subject_id?}`: send an alert |
| POST | `/api/notify/bulk` | `{subject_id?, notify_parents?}`: alert everyone below the minimum |
