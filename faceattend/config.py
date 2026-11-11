import os
import secrets
from datetime import timedelta
from pathlib import Path

from cryptography.fernet import Fernet

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


def _persisted(filename, create):
    """Read a secret from instance/, creating it on first run. Use environment variables in production."""
    path = INSTANCE_DIR / filename
    if not path.exists():
        path.write_text(create())
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_text().strip()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or _persisted("secret_key.txt", lambda: secrets.token_hex(32))
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", f"sqlite:///{INSTANCE_DIR / 'attendance.db'}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Fernet key that encrypts face templates at rest. If it is lost, enrolled faces must be re-captured.
    FACE_KEY = os.environ.get("FACE_ENCRYPTION_KEY") or _persisted(
        "face_key.txt", lambda: Fernet.generate_key().decode()
    )
    # Euclidean distance between 128-d encodings (lower = more similar).
    MATCH_THRESHOLD = float(os.environ.get("MATCH_THRESHOLD", "0.5"))    # auto-mark at or below this
    REVIEW_THRESHOLD = float(os.environ.get("REVIEW_THRESHOLD", "0.6"))  # teacher review up to this

    LATE_AFTER = os.environ.get("LATE_AFTER", "09:15")
    SCHOOL_NAME = os.environ.get("SCHOOL_NAME", "Your School")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024
