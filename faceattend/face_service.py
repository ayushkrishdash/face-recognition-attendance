"""Face detection, encoding, encryption and matching.

Photos are processed in memory and discarded. Only an encrypted 128-d encoding is stored.
Note: this module does not perform liveness detection, so a printed photo held up to the
camera could be accepted. See README "Known limitations".
"""
import io

import numpy as np
from cryptography.fernet import Fernet
from flask import current_app

FACE_MESSAGES = {
    "no_face": "No face detected. Look at the camera in good light.",
    "multiple_faces": "More than one face is visible. Only one student should be in frame.",
    "face_too_small": "Face is too far from the camera. Move closer.",
}
MIN_FACE_PX = 80


def _face_recognition():
    # Imported lazily so the rest of the app (and its tests) runs without dlib installed.
    import face_recognition
    return face_recognition


def extract_single_encoding(image_bytes):
    """Return (encoding, None) for exactly one usable face, or (None, problem_code)."""
    fr = _face_recognition()
    image = fr.load_image_file(io.BytesIO(image_bytes))
    locations = fr.face_locations(image, model="hog")
    if not locations:
        return None, "no_face"
    if len(locations) > 1:
        return None, "multiple_faces"
    top, right, bottom, left = locations[0]
    if min(bottom - top, right - left) < MIN_FACE_PX:
        return None, "face_too_small"
    encoding = fr.face_encodings(image, locations)[0]
    return encoding, None


def _fernet():
    return Fernet(current_app.config["FACE_KEY"].encode())


def encrypt_template(encoding):
    return _fernet().encrypt(np.asarray(encoding, dtype=np.float64).tobytes())


def decrypt_template(token):
    return np.frombuffer(_fernet().decrypt(token), dtype=np.float64)


def rank_matches(encoding, students):
    """Return [(student, distance)] for enrolled students, closest first."""
    enrolled = [(s, decrypt_template(s.face_template)) for s in students if s.face_template]
    if not enrolled:
        return []
    matrix = np.vstack([template for _, template in enrolled])
    distances = np.linalg.norm(matrix - np.asarray(encoding, dtype=np.float64), axis=1)
    ranked = [(student, float(d)) for (student, _), d in zip(enrolled, distances)]
    ranked.sort(key=lambda pair: pair[1])
    return ranked


def classify(ranked, match_threshold, review_threshold, ambiguity_margin=0.04):
    """Return (outcome, top_pair, top_candidates). Outcome is match, review or unknown."""
    if not ranked:
        return "unknown", None, []
    best_student, best = ranked[0]
    candidates = ranked[:3]
    if best > review_threshold:
        return "unknown", None, []
    if best <= match_threshold:
        # Two near-identical matches (e.g. twins) are never auto-marked.
        runner_up_gap = ranked[1][1] - best if len(ranked) > 1 else None
        if runner_up_gap is None or runner_up_gap >= ambiguity_margin:
            return "match", ranked[0], candidates
    return "review", ranked[0], candidates
