"""Create, refresh or remove the development test student "Test Student" (TEST001).

Usage:
  python seed_test_student.py /path/to/photo.jpg   # create or refresh the test profile and face
  python seed_test_student.py --remove-face        # delete only the face template, keep the profile
  python seed_test_student.py --remove             # delete the profile, attendance and face data

Only use a photo of a person who has given permission. The photo is read into memory,
converted to an encrypted template, and discarded. It is never copied into the project.
"""
import argparse
from datetime import datetime
from pathlib import Path

import face_service
from app import create_app
from models import Student, db, log_action

ROLL = "TEST001"
NAME = "Test Student"
CLASS = "DEV"
SECTION = "T"


def enrol_from_photo(photo_path):
    image = Path(photo_path).read_bytes()
    encoding, problem = face_service.extract_single_encoding(image)
    del image
    if problem:
        raise SystemExit(f"Photo rejected: {face_service.FACE_MESSAGES[problem]}")
    return encoding


def seed(photo_path):
    encoding = enrol_from_photo(photo_path)
    student = Student.query.filter_by(roll_no=ROLL).first() or Student(roll_no=ROLL)
    student.full_name = NAME
    student.class_name = CLASS
    student.section = SECTION
    student.is_minor = False
    student.parental_consent = False
    student.consent_recorded_at = student.consent_recorded_at or datetime.now()
    student.face_template = face_service.encrypt_template(encoding)
    student.face_enrolled_at = datetime.now()
    db.session.add(student)
    log_action("test_profile_seeded", ROLL)
    db.session.commit()
    return student


def remove_face():
    student = Student.query.filter_by(roll_no=ROLL).first()
    if not student:
        return False
    student.face_template = None
    student.face_enrolled_at = None
    log_action("test_face_removed", ROLL)
    db.session.commit()
    return True


def remove_profile():
    student = Student.query.filter_by(roll_no=ROLL).first()
    if not student:
        return False
    db.session.delete(student)  # cascades to attendance and the face template
    log_action("test_profile_removed", ROLL)
    db.session.commit()
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("photo", nargs="?", help="JPEG/PNG of the consenting test person")
    parser.add_argument("--remove", action="store_true", help="delete the test profile and all its data")
    parser.add_argument("--remove-face", action="store_true", help="delete only the biometric template")
    args = parser.parse_args()

    if args.remove:
        choice = "removed" if remove_profile() else "not found, nothing to remove"
        print(f"Test profile {choice}.")
        return
    if args.remove_face:
        choice = "face data deleted" if remove_face() else "not found"
        print(f"Test profile {choice}.")
        return
    if not args.photo:
        parser.error("provide a photo path, or use --remove / --remove-face")

    app = create_app()
    with app.app_context():
        student = seed(args.photo)
        print(f"Enrolled {student.full_name} ({student.roll_no}). Face data is encrypted; the photo was not stored.")


if __name__ == "__main__":
    main()
