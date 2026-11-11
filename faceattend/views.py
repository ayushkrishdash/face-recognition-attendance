from datetime import datetime

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   session, url_for)
from sqlalchemy import distinct, func, or_
from werkzeug.security import check_password_hash

import face_service
import reports
from auth import login_required, role_required
from models import Attendance, Student, User, db, log_action

bp = Blueprint("views", __name__)
STAFF = ("admin", "teacher")


def _class_names():
    return [c for (c,) in db.session.query(Student.class_name).distinct().order_by(Student.class_name).all()]


# ---------- Auth ----------

@bp.get("/")
def index():
    return redirect(url_for("views.dashboard") if g.user else url_for("views.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("views.dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()[:64]
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username, is_active=True).first()
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.id
            session.permanent = True
            log_action("login", username, user.id)
            db.session.commit()
            nxt = request.args.get("next", "")
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("views.dashboard")
            return redirect(nxt)
        log_action("login_failed", username)
        db.session.commit()
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    if g.user:
        log_action("logout", g.user.username, g.user.id)
        db.session.commit()
    session.clear()
    return redirect(url_for("views.login"))


# ---------- Pages ----------

@bp.get("/dashboard")
@role_required(*STAFF)
def dashboard():
    return render_template("dashboard.html")


@bp.get("/attendance")
@role_required(*STAFF)
def attendance():
    return render_template("attendance.html")


@bp.get("/records")
@role_required(*STAFF)
def records():
    rows = reports.build_rows(request.args)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("present", "late", "absent")}
    return render_template(
        "records.html", rows=rows, counts=counts, classes=_class_names(),
        single_day=reports.is_single_day(request.args), qs=request.query_string.decode(),
    )


@bp.get("/records/export")
@role_required(*STAFF)
def records_export():
    fmt = request.args.get("format", "csv")
    if fmt not in ("csv", "xlsx"):
        abort(400)
    rows = reports.build_rows(request.args)
    log_action("export", f"{fmt}: {len(rows)} rows", g.user.id)
    db.session.commit()
    return reports.export(rows, fmt)


# ---------- Students ----------

@bp.get("/students")
@role_required(*STAFF)
def students():
    q = request.args.get("q", "").strip()[:64]
    class_name = request.args.get("class_name", "").strip()
    query = Student.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Student.full_name.ilike(like), Student.roll_no.ilike(like)))
    if class_name:
        query = query.filter_by(class_name=class_name)
    rows = query.order_by(Student.class_name, Student.roll_no).all()
    return render_template("students.html", students=rows, classes=_class_names(), q=q, class_name=class_name)


def _parse_student_form(form, student_id=None):
    data = {
        "full_name": form.get("full_name", "").strip(),
        "roll_no": form.get("roll_no", "").strip(),
        "class_name": form.get("class_name", "").strip(),
        "section": form.get("section", "").strip(),
        "is_minor": form.get("is_minor") == "on",
        "parental_consent": form.get("parental_consent") == "on",
        "consent_confirmed": form.get("consent_confirmed") == "on",
    }
    errors = []
    if not data["full_name"] or len(data["full_name"]) > 120:
        errors.append("Full name is required (maximum 120 characters).")
    if not data["roll_no"] or len(data["roll_no"]) > 32:
        errors.append("Roll number is required (maximum 32 characters).")
    if not data["class_name"] or len(data["class_name"]) > 32:
        errors.append("Class is required (maximum 32 characters).")
    if len(data["section"]) > 8:
        errors.append("Section must be 8 characters or fewer.")
    if data["roll_no"]:
        clash = Student.query.filter(Student.roll_no == data["roll_no"])
        if student_id:
            clash = clash.filter(Student.id != student_id)
        if clash.first():
            errors.append(f"Roll number {data['roll_no']} is already registered.")
    return data, errors


def _apply_consent(student, data):
    student.is_minor = data["is_minor"]
    student.parental_consent = data["parental_consent"]
    if data["consent_confirmed"]:
        student.consent_recorded_at = student.consent_recorded_at or datetime.now()
    else:
        # Withdrawing consent deletes the face profile immediately.
        if student.face_template:
            log_action("consent_withdrawn", student.roll_no, g.user.id)
        student.consent_recorded_at = None
        student.face_template = None
        student.face_enrolled_at = None


def _consent_problem(student):
    if not student.consent_recorded_at:
        return "record informed consent before capturing a face."
    if student.is_minor and not student.parental_consent:
        return "parental or guardian consent is required for students under 18."
    return None


def _enroll_from_upload(student, upload):
    """Return (category, message) or None if no image was submitted. The photo is discarded."""
    if upload is None or not upload.filename:
        return None
    problem = _consent_problem(student)
    if problem:
        return ("warning", f"Face not saved: {problem}")
    image = upload.read()
    try:
        encoding, issue = face_service.extract_single_encoding(image)
    except Exception:
        current_app.logger.exception("Face enrolment failed")
        return ("error", "Face could not be processed right now. Try again or enrol later.")
    if issue:
        return ("warning", f"Face not saved: {face_service.FACE_MESSAGES[issue]}")
    student.face_template = face_service.encrypt_template(encoding)
    student.face_enrolled_at = datetime.now()
    log_action("face_enrolled", student.roll_no, g.user.id)
    return ("success", "Face profile enrolled and encrypted.")


def _student_values(s):
    if s is None:
        return {}
    return {"full_name": s.full_name, "roll_no": s.roll_no, "class_name": s.class_name,
            "section": s.section or "", "is_minor": s.is_minor, "parental_consent": s.parental_consent,
            "consent_confirmed": bool(s.consent_recorded_at)}


@bp.route("/students/new", methods=["GET", "POST"])
@role_required("admin")
def student_new():
    if request.method == "POST":
        data, errors = _parse_student_form(request.form)
        if not errors:
            student = Student(full_name=data["full_name"], roll_no=data["roll_no"],
                              class_name=data["class_name"], section=data["section"])
            db.session.add(student)
            _apply_consent(student, data)
            db.session.flush()
            result = _enroll_from_upload(student, request.files.get("face_image"))
            log_action("student_created", student.roll_no, g.user.id)
            db.session.commit()
            flash(f"{student.full_name} registered.", "success")
            if result:
                flash(result[1], result[0])
            return redirect(url_for("views.student_detail", student_id=student.id))
        for error in errors:
            flash(error, "error")
        return render_template("student_form.html", student=None, values=request.form)
    return render_template("student_form.html", student=None, values={})


@bp.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def student_edit(student_id):
    student = db.get_or_404(Student, student_id)
    if request.method == "POST":
        data, errors = _parse_student_form(request.form, student.id)
        if not errors:
            student.full_name = data["full_name"]
            student.roll_no = data["roll_no"]
            student.class_name = data["class_name"]
            student.section = data["section"]
            _apply_consent(student, data)
            result = _enroll_from_upload(student, request.files.get("face_image"))
            log_action("student_updated", student.roll_no, g.user.id)
            db.session.commit()
            flash("Student profile updated.", "success")
            if result:
                flash(result[1], result[0])
            return redirect(url_for("views.student_detail", student_id=student.id))
        for error in errors:
            flash(error, "error")
        return render_template("student_form.html", student=student, values=request.form)
    return render_template("student_form.html", student=student, values=_student_values(student))


@bp.get("/students/<int:student_id>")
@role_required(*STAFF)
def student_detail(student_id):
    student = db.get_or_404(Student, student_id)
    records_list = (Attendance.query.filter_by(student_id=student.id)
                    .order_by(Attendance.date.desc()).all())
    school_days = db.session.query(func.count(distinct(Attendance.date))).scalar() or 0
    present_days = len(records_list)
    return render_template(
        "student_detail.html", student=student, records=records_list,
        percent=round(present_days * 100 / school_days, 1) if school_days else 0.0,
        absent_days=max(school_days - present_days, 0),
    )


@bp.post("/students/<int:student_id>/face")
@role_required("admin")
def student_face(student_id):
    student = db.get_or_404(Student, student_id)
    result = _enroll_from_upload(student, request.files.get("face_image"))
    if result is None:
        flash("Capture a face before saving.", "error")
    else:
        if result[0] == "success":
            db.session.commit()
        flash(result[1], result[0])
    return redirect(url_for("views.student_detail", student_id=student.id))


@bp.post("/students/<int:student_id>/face/remove")
@role_required("admin")
def student_face_remove(student_id):
    student = db.get_or_404(Student, student_id)
    student.face_template = None
    student.face_enrolled_at = None
    log_action("face_removed", student.roll_no, g.user.id)
    db.session.commit()
    flash("Face profile deleted. Attendance records were kept.", "success")
    return redirect(url_for("views.student_detail", student_id=student.id))


@bp.post("/students/<int:student_id>/delete")
@role_required("admin")
def student_delete(student_id):
    student = db.get_or_404(Student, student_id)
    label = f"{student.roll_no} {student.full_name}"
    db.session.delete(student)
    log_action("student_deleted", label, g.user.id)
    db.session.commit()
    flash(f"{label} was removed, along with their attendance history and face data.", "success")
    return redirect(url_for("views.students"))
