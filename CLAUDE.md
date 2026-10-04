# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

FaceMark is a face-recognition attendance system backed by MySQL (database `attendance_system`). See README.md for the user-facing summary and benchmarks/README.md for measured results. The owner uses this project for interviews and wants it **kept simple**: prefer removing code over adding abstractions, and don't add features or tables that nothing uses.

## Commands

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt   # dlib compiles (needs cmake); dlib may not build on 3.14
cp .env.example .env                                                     # all settings come from .env via config.py
mysql -u root -p attendance_system < schema.sql                          # 10 tables + seed data

.venv/bin/pytest                                                          # unit tests, no DB or camera needed
.venv/bin/pytest tests/test_face_matching.py::test_match_within_tolerance

.venv/bin/python register_faces.py   # enroll sample_faces/<User.Name>/*.jpg
.venv/bin/python attendance.py       # demo: session for subject 1009, webcam loop, then close it
.venv/bin/python api.py              # FastAPI via uvicorn on API_PORT (macOS AirPlay holds 5000, so use 5050); docs at /docs
.venv/bin/python scheduler.py        # closes finished sessions every 5 min, optional daily emails

.venv/bin/python benchmarks/eval_recognition.py   # LFW accuracy → benchmarks/results/
.venv/bin/python benchmarks/eval_performance.py   # speed (--webcam for real frames)
.venv/bin/python benchmarks/eval_system.py        # pooled vs fresh DB connections (needs MySQL)
```

`face_recognition_models` imports `pkg_resources`, so `setuptools<81` is pinned.

## Architecture

- **`face_matching.py`** is the core and has no DB or camera code. It holds `encode_largest_face`, `FaceMatcher` (vectorized nearest neighbor; `mean` averages a student's photos, `min` uses the closest photo) and `ConfirmationTracker` (N consecutive matches before marking). The app and the benchmarks both import it; change matching behavior here.
- **`database.py`**: `DatabaseManager` is a singleton connection pool. `transaction()` yields a dict cursor and commits/rolls back as a unit, and `execute_query()` is a one-statement wrapper over it. Never open connections elsewhere.
- **`attendance.py`**: `create_session` and `close_session(db, id)` are plain functions; the API and scheduler use them without loading faces. `close_session` inserts `Absent` rows for enrolled students (`Student_Subject`) with no row and sets `Completed`, in one transaction. The `MarkAttendance` class loads all embeddings into memory, and `recognize_user` runs the camera loop (`FRAME_SCALE`, `FRAME_SKIP`, `CONFIRM_FRAMES`). `compute_status` decides Present vs Late.
- **`users.py`**: `create_student` (User + Students + Student_Subject) and `create_faculty` (User + Faculty), each in one transaction. Behind `POST /api/students` and `/api/faculty`; `api.py` maps MySQL IntegrityError to 409 (duplicate) or 400 (unknown class/subject id).
- **`notifications.py`**: `ATTENDANCE_QUERY` computes every student's attendance in one `GROUP BY` over Attendance rows in `Completed` sessions. This relies on `close_session` having written Absent rows. Emails go out over SMTP (587 STARTTLS, or 465 SSL).
- **`config.py`** reads `.env`. The `Attendance_Settings` table (`late_threshold_minutes`, `min_attendance_percentage`) overrides the matching `Config` values at runtime.
- **Schema (10 tables):** `User` is extended by `Students` (Parent_Email, Class_ID) or `Faculty`. `Subject.User_ID` is the teacher. `Student_Subject` holds enrollment. `Attendance` has `UNIQUE (User_ID, Session_ID)` and an FK to `Students`, so recognized faculty can't be marked.

## Benchmarks

`eval_recognition.py` runs open-set identification on LFW, downloaded from a Hugging Face parquet mirror because scikit-learn's figshare mirror returns 403. Encodings are cached in `benchmarks/cache/`; delete it after changing detection/encoding. The `config.py` defaults (`mean`, tolerance 0.43) come from that run and assume ~5 photos per student; with 1 photo, 0.48 is right. If matching code or defaults change, re-run the benchmarks and update benchmarks/README.md and README.md.

## Conventions

Python names are snake_case; SQL tables and columns are `Pascal_Snake` (`User_ID`). Query results are dicts keyed by column name (or by the SQL alias).
