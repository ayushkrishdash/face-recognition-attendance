"""End-to-end tests for registration, verification, duplicates, review, manual marking and reports.

Face *detection* is stubbed (no dlib needed): each "image" is a 128-d float64 vector. Everything
else, including encryption, matching, thresholds, duplicate prevention and exports, is real.
"""
import io
from datetime import date

import numpy as np
import pytest
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

import face_service
from app import create_app
from models import Attendance, Student, User, db

RNG = np.random.default_rng(7)


def fake_extract(image_bytes):
    if not image_bytes:
        return None, "no_face"
    return np.frombuffer(image_bytes, dtype=np.float64).copy(), None


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(face_service, "extract_single_encoding", fake_extract)
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "FACE_KEY": Fernet.generate_key().decode(),
        "LATE_AFTER": "23:59",
    })
    with app.app_context():
        db.session.add_all([
            User(username="admin", full_name="Admin", role="admin",
                 password_hash=generate_password_hash("admin-pass-123")),
            User(username="teacher", full_name="Teacher", role="teacher",
                 password_hash=generate_password_hash("teacher-pass-123")),
        ])
        db.session.commit()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def token(client):
    with client.session_transaction() as s:
        s.setdefault("csrf_token", "test-token")
        return s["csrf_token"]


def csrf_header(client):
    return {"X-CSRF-Token": token(client)}


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password,
                                       "csrf_token": token(client)})


def register(client, roll="R001", name="Asha Rao", consent=True, face=None, minor=False, parental=False):
    data = {"csrf_token": token(client), "full_name": name, "roll_no": roll,
            "class_name": "10", "section": "A"}
    if consent:
        data["consent_confirmed"] = "on"
    if minor:
        data["is_minor"] = "on"
    if parental:
        data["parental_consent"] = "on"
    if face is not None:
        data["face_image"] = (io.BytesIO(face.tobytes()), "face.jpg")
    return client.post("/students/new", data=data, content_type="multipart/form-data")


def verify(client, vector):
    response = client.post(
        "/api/attendance/verify",
        data={"image": (io.BytesIO(vector.tobytes()), "frame.jpg")},
        headers=csrf_header(client),
        content_type="multipart/form-data",
    )
    return response.get_json()


def student_id(app, roll):
    with app.app_context():
        return Student.query.filter_by(roll_no=roll).one().id


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_wrong_password_is_rejected(client):
    login(client, "admin", "wrong-password")
    assert client.get("/dashboard").status_code == 302


def test_teacher_cannot_register_students(app, client):
    login(client, "teacher", "teacher-pass-123")
    assert register(client, roll="T1").status_code == 403
    with app.app_context():
        assert Student.query.count() == 0


def test_face_is_not_enrolled_without_consent(app, client):
    login(client, "admin", "admin-pass-123")
    register(client, roll="R100", consent=False, face=RNG.normal(size=128) * 0.1)
    with app.app_context():
        student = Student.query.filter_by(roll_no="R100").one()
        assert student.face_template is None


def test_enrol_verify_duplicate_and_unknown(app, client):
    login(client, "admin", "admin-pass-123")
    vector = RNG.normal(size=128) * 0.1
    assert register(client, roll="R001", face=vector).status_code == 302

    with app.app_context():
        template = Student.query.filter_by(roll_no="R001").one().face_template
        assert template is not None
        assert template != vector.tobytes()  # stored encrypted, not as raw data

    first = verify(client, vector)
    assert first["status"] == "marked"
    assert first["student"]["roll_no"] == "R001"
    assert first["message"] == "Attendance Marked Successfully"

    second = verify(client, vector)
    assert second["status"] == "duplicate"
    with app.app_context():
        assert Attendance.query.count() == 1

    stranger = RNG.normal(size=128) * 0.1
    assert verify(client, stranger)["status"] == "unknown"


def test_uncertain_match_requires_teacher_confirmation(app, client):
    login(client, "admin", "admin-pass-123")
    vector = RNG.normal(size=128) * 0.1
    register(client, roll="R002", face=vector)

    noise = RNG.normal(size=128)
    noise = noise / np.linalg.norm(noise) * 0.55  # distance 0.55: between match (0.5) and review (0.6)
    result = verify(client, vector + noise)
    assert result["status"] == "review"
    candidate_id = result["candidates"][0]["student"]["id"]
    assert result["candidates"][0]["student"]["roll_no"] == "R002"
    with app.app_context():
        assert Attendance.query.count() == 0  # nothing marked until confirmed

    confirmed = client.post("/api/attendance/confirm", json={"student_id": candidate_id},
                            headers=csrf_header(client)).get_json()
    assert confirmed["status"] == "marked"
    with app.app_context():
        assert Attendance.query.one().method == "face_reviewed"


def test_manual_attendance_reports_and_csv_safety(app, client):
    login(client, "admin", "admin-pass-123")
    vec_a = RNG.normal(size=128) * 0.1
    vec_b = RNG.normal(size=128) * 0.1
    register(client, roll="R010", name="Ravi Kumar", face=vec_a)
    register(client, roll="R011", name="Meera Joshi", face=vec_b)
    register(client, roll="R012", name="=1+1", consent=False)  # no face, formula-like name

    assert verify(client, vec_a)["status"] == "marked"
    manual_id = student_id(app, "R011")
    manual = client.post("/api/attendance/manual", json={"student_id": manual_id},
                         headers=csrf_header(client)).get_json()
    assert manual["status"] == "marked"
    assert client.post("/api/attendance/manual", json={"student_id": manual_id},
                       headers=csrf_header(client)).get_json()["status"] == "duplicate"

    today = date.today().isoformat()
    csv_response = client.get(f"/records/export?format=csv&date_from={today}&date_to={today}")
    assert csv_response.status_code == 200
    assert csv_response.mimetype == "text/csv"
    body = csv_response.data.decode("utf-8-sig")
    assert "R010" in body and "R011" in body
    assert "manual" in body
    assert "absent" in body          # R012 has no record today
    assert "'=1+1" in body           # formula injection neutralised

    xlsx_response = client.get(f"/records/export?format=xlsx&date_from={today}&date_to={today}")
    assert xlsx_response.status_code == 200
    assert xlsx_response.data[:2] == b"PK"  # valid zip-based .xlsx


def test_delete_student_removes_history_and_face_data(app, client):
    login(client, "admin", "admin-pass-123")
    vector = RNG.normal(size=128) * 0.1
    register(client, roll="R020", face=vector)
    verify(client, vector)
    sid = student_id(app, "R020")

    response = client.post(f"/students/{sid}/delete", data={"csrf_token": token(client)})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Student, sid) is None
        assert Attendance.query.count() == 0


def test_withdrawing_consent_deletes_face_template(app, client):
    login(client, "admin", "admin-pass-123")
    register(client, roll="R030", face=RNG.normal(size=128) * 0.1)
    sid = student_id(app, "R030")

    client.post(f"/students/{sid}/edit", data={
        "csrf_token": token(client), "full_name": "Asha Rao", "roll_no": "R030",
        "class_name": "10", "section": "A",   # consent_confirmed omitted = withdrawn
    }, content_type="multipart/form-data")
    with app.app_context():
        student = db.session.get(Student, sid)
        assert student.face_template is None
        assert student.consent_recorded_at is None


def test_seed_script_enrols_test_student_and_removes_data(app, tmp_path):
    import seed_test_student as seed_tool

    photo = tmp_path / "photo.jpg"
    photo.write_bytes((RNG.normal(size=128) * 0.1).tobytes())
    with app.app_context():
        student = seed_tool.seed(str(photo))
        assert student.roll_no == "TEST001"
        assert student.full_name == "Test Student"
        assert student.face_template is not None
        assert seed_tool.remove_face() is True
        assert Student.query.filter_by(roll_no="TEST001").one().face_template is None
        assert seed_tool.remove_profile() is True
        assert Student.query.filter_by(roll_no="TEST001").first() is None
