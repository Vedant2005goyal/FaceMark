import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """All settings come from environment variables (or a local .env file)."""

    # Database
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 3306))
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_NAME = os.getenv('DB_NAME', 'attendance_system')

    # Email (Gmail needs an App Password)
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SENDER_EMAIL = os.getenv('SENDER_EMAIL', '')
    SENDER_PASSWORD = os.getenv('SENDER_PASSWORD', '')

    # Face recognition. Tolerance and strategy were tuned on LFW (see benchmarks/README.md):
    # 0.43 with the mean of ~5 photos per student keeps false accepts under 1%.
    # With only 1 photo per student use 0.48 instead.
    FACE_RECOGNITION_TOLERANCE = float(os.getenv('FACE_RECOGNITION_TOLERANCE', 0.43))
    FACE_MATCH_STRATEGY = os.getenv('FACE_MATCH_STRATEGY', 'mean')  # 'mean' or 'min' over a student's photos
    MAX_EMBEDDINGS_PER_USER = int(os.getenv('MAX_EMBEDDINGS_PER_USER', 5))
    FACE_DETECTION_MODEL = os.getenv('FACE_DETECTION_MODEL', 'hog')  # 'hog' (fast, CPU) or 'cnn' (needs GPU)

    # Webcam loop
    FRAME_SCALE = float(os.getenv('FRAME_SCALE', 0.25))  # downscale frames before detection
    FRAME_SKIP = int(os.getenv('FRAME_SKIP', 2))  # run recognition on every Nth frame
    CONFIRM_FRAMES = int(os.getenv('CONFIRM_FRAMES', 3))  # consecutive matches needed to mark attendance

    # Attendance rules (fallbacks; the Attendance_Settings table overrides these at runtime)
    LATE_THRESHOLD_MINUTES = int(os.getenv('LATE_THRESHOLD_MINUTES', 10))
    MIN_ATTENDANCE_PERCENTAGE = int(os.getenv('MIN_ATTENDANCE_PERCENTAGE', 75))

    # Automation
    AUTO_NOTIFY_ENABLED = os.getenv('AUTO_NOTIFY_ENABLED', 'false').lower() == 'true'
    AUTO_NOTIFY_SCHEDULE = os.getenv('AUTO_NOTIFY_SCHEDULE', '18:00')  # daily, 24h clock

    # API (macOS AirPlay Receiver occupies 5000; set API_PORT=5050 locally)
    API_PORT = int(os.getenv('API_PORT', 5000))

    @classmethod
    def validate(cls):
        """Fail fast at startup if required settings are missing."""
        required = {'DB_PASSWORD': cls.DB_PASSWORD, 'SENDER_EMAIL': cls.SENDER_EMAIL,
                    'SENDER_PASSWORD': cls.SENDER_PASSWORD}
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required config: {', '.join(missing)}")
