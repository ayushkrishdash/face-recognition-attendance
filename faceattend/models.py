from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="teacher")  # admin | teacher
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    roll_no = db.Column(db.String(32), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    class_name = db.Column(db.String(32), nullable=False, index=True)
    section = db.Column(db.String(8), default="")
    is_minor = db.Column(db.Boolean, default=False)
    parental_consent = db.Column(db.Boolean, default=False)
    consent_recorded_at = db.Column(db.DateTime)
    # Fernet-encrypted 128-d face encoding. Photos are never stored.
    face_template = db.Column(db.LargeBinary)
    face_enrolled_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    attendance = db.relationship(
        "Attendance", back_populates="student", cascade="all, delete-orphan", passive_deletes=True
    )


class Attendance(db.Model):
    __tablename__ = "attendance"
    __table_args__ = (db.UniqueConstraint("student_id", "date", name="uq_attendance_student_day"),)
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    check_in = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(16), nullable=False)   # present | late  (absent = no row)
    method = db.Column(db.String(24), nullable=False)   # face | face_reviewed | manual
    confidence = db.Column(db.Float)                    # face distance, lower is closer
    marked_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    student = db.relationship("Student", back_populates="attendance")


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(48), nullable=False)
    detail = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


def log_action(action, detail="", user_id=None):
    """Adds an audit entry to the current session. The caller commits. Biometric data is never logged."""
    db.session.add(AuditLog(user_id=user_id, action=action, detail=str(detail)[:255]))
