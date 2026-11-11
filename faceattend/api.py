from datetime import date, datetime, time, timedelta

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import face_service
from auth import role_required
from models import Attendance, Student, db, log_action

bp = Blueprint("api", __name__)
STAFF = ("admin", "teacher")


def _student_json(s):
    return {"id": s.id, "roll_no": s.roll_no, "full_name": s.full_name,
            "class_name": s.class_name, "section": s.section or ""}


def _attendance_json(a):
    return {"id": a.id, "student": _student_json(a.student), "date": a.date.isoformat(),
            "check_in": a.check_in.strftime("%H:%M:%S"), "status": a.status, "method": a.method}


def _late_cutoff():
    hour, minute = current_app.config["LATE_AFTER"].split(":")
    return time(int(hour), int(minute))


def mark_attendance(student, method, user_id, confidence=None):
    """Create today's record once per student. Returns (record, created)."""
    today = date.today()
    existing = Attendance.query.filter_by(student_id=student.id, date=today).first()
    if existing:
        return existing, False
    now = datetime.now()
    record = Attendance(
        student_id=student.id, date=today, check_in=now,
        status="late" if now.time() > _late_cutoff() else "present",
        method=method, confidence=confidence, marked_by=user_id,
    )
    db.session.add(record)
    log_action("attendance_marked", f"{student.roll_no} {method}", user_id)
    try:
        db.session.commit()
    except IntegrityError:
        # A concurrent request marked this student first. The unique constraint is the final guard.
        db.session.rollback()
        return Attendance.query.filter_by(student_id=student.id, date=today).one(), False
    return record, True


def _marked_response(student, record, created):
    payload = {"student": _student_json(student), "attendance": _attendance_json(record)}
    if created:
        return {"status": "marked", "message": "Attendance Marked Successfully", **payload}
    return {"status": "duplicate", "message": f"{student.full_name} is already marked for today.", **payload}


def _student_from_body():
    body = request.get_json(silent=True) or {}
    try:
        return db.session.get(Student, int(body.get("student_id")))
    except (TypeError, ValueError):
        return None


@bp.post("/attendance/verify")
@role_required(*STAFF)
def verify():
    upload = request.files.get("image")
    if upload is None:
        return {"status": "error", "message": "No camera frame received."}, 400
    image = upload.read()
    try:
        encoding, problem = face_service.extract_single_encoding(image)
    except Exception:
        current_app.logger.exception("Face processing failed")
        return {"status": "error", "message": "Face recognition is unavailable. Use manual attendance."}, 503
    finally:
        del image  # frames are never retained

    if problem:
        return {"status": problem, "message": face_service.FACE_MESSAGES[problem]}

    enrolled = Student.query.filter(Student.face_template.isnot(None)).all()
    ranked = face_service.rank_matches(encoding, enrolled)
    outcome, top, candidates = face_service.classify(
        ranked, current_app.config["MATCH_THRESHOLD"], current_app.config["REVIEW_THRESHOLD"]
    )

    if outcome == "match":
        student, distance = top
        record, created = mark_attendance(student, "face", g.user.id, confidence=round(distance, 3))
        return _marked_response(student, record, created)

    if outcome == "review":
        log_action("face_review_required", "uncertain match", g.user.id)
        db.session.commit()
        return {
            "status": "review",
            "message": "Uncertain match. Confirm the correct student or dismiss.",
            "candidates": [{"student": _student_json(s), "distance": round(d, 3)} for s, d in candidates],
        }

    return {"status": "unknown", "message": "Unknown Student"}


@bp.post("/attendance/confirm")
@role_required(*STAFF)
def confirm():
    """Teacher confirms a reviewed (uncertain) face match."""
    student = _student_from_body()
    if student is None:
        return {"status": "error", "message": "Student not found."}, 404
    if not student.face_template:
        return {"status": "error", "message": "This student has no enrolled face to confirm against."}, 400
    record, created = mark_attendance(student, "face_reviewed", g.user.id)
    return _marked_response(student, record, created)


@bp.post("/attendance/manual")
@role_required(*STAFF)
def manual():
    """Manual attendance for students who lack consent, a face profile, or when the camera fails."""
    student = _student_from_body()
    if student is None:
        return {"status": "error", "message": "Student not found."}, 404
    record, created = mark_attendance(student, "manual", g.user.id)
    return _marked_response(student, record, created)


@bp.get("/attendance/today")
@role_required(*STAFF)
def today_list():
    today = date.today()
    records = Attendance.query.filter_by(date=today).order_by(Attendance.check_in.desc()).all()
    marked_ids = [r.student_id for r in records]
    unmarked_query = Student.query
    if marked_ids:
        unmarked_query = unmarked_query.filter(~Student.id.in_(marked_ids))
    unmarked = unmarked_query.order_by(Student.roll_no).all()
    return {
        "date": today.isoformat(),
        "records": [_attendance_json(r) for r in records],
        "unmarked": [{**_student_json(s), "enrolled": bool(s.face_template)} for s in unmarked],
    }


@bp.get("/dashboard/stats")
@role_required(*STAFF)
def dashboard_stats():
    today = date.today()
    total = Student.query.count()
    enrolled = Student.query.filter(Student.face_template.isnot(None)).count()
    todays = Attendance.query.filter_by(date=today).all()
    present = len(todays)
    late = sum(1 for a in todays if a.status == "late")
    absent = max(total - present, 0)
    percent = round(present * 100 / total, 1) if total else 0.0

    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    counts = dict(
        db.session.query(Attendance.date, func.count(Attendance.id))
        .filter(Attendance.date >= days[0])
        .group_by(Attendance.date)
        .all()
    )
    recent = Attendance.query.order_by(Attendance.check_in.desc()).limit(10).all()
    return {
        "totals": {"total": total, "enrolled": enrolled, "present": present,
                   "late": late, "absent": absent, "percent": percent},
        "trend": {"labels": [d.strftime("%a %d %b") for d in days],
                  "present": [counts.get(d, 0) for d in days]},
        "recent": [_attendance_json(a) for a in recent],
        "generated_at": datetime.now().strftime("%H:%M:%S"),
    }
