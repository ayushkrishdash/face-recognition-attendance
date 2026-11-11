# FaceAttend: face-recognition attendance for schools and colleges

Flask + SQLAlchemy backend, browser camera via getUserMedia, face matching with the `face_recognition` library.

## Features
- Admin and teacher login with role-based access, CSRF protection, session expiry, and logout.
- Dashboard: registered, present, absent and late counts, attendance rate, 7-day trend, live activity, recent records.
- Student registration with consent recording and camera-based face enrolment. Edit, view history, delete.
- Attendance page: live camera, automatic verification, "Attendance Marked Successfully", duplicate prevention, "Unknown Student", teacher review of uncertain matches, and manual attendance.
- Records with search and filters. Export to CSV and Excel, including absent students for a single date.
- Audit log of logins, enrolments, attendance marks, exports and deletions. Biometric data is never logged.

## 1. Install
Requires Python 3.10+. Building `dlib` (used by `face_recognition`) needs CMake and a C++ compiler.
- Ubuntu/Debian: `sudo apt install build-essential cmake libopenblas-dev liblapack-dev`
- macOS: `brew install cmake`
- Windows: install Visual Studio Build Tools and CMake, or use a prebuilt `dlib` wheel.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Create the first admin
```bash
flask --app app create-user --username admin --name "Principal" --role admin
flask --app app create-user --username ms.rao --name "Ms. Rao" --role teacher
```
Passwords must be at least 10 characters.

## 3. Run
```bash
python app.py          # http://127.0.0.1:5000
```
Browsers only allow camera access on `localhost` or HTTPS. For use on other devices, put the app behind an HTTPS reverse proxy (Caddy or nginx with a certificate). Do not expose plain HTTP on a network.

## 4. Database configuration
- Default: SQLite at `instance/attendance.db`. Good for a single-school pilot.
- MySQL: create the database (`CREATE DATABASE faceattend CHARACTER SET utf8mb4;`) and set
  `DATABASE_URL=mysql+pymysql://user:password@localhost/faceattend`. Tables are created automatically on first start.

## 5. Environment variables (set these in production)
| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Session signing | generated into `instance/secret_key.txt` |
| `FACE_ENCRYPTION_KEY` | Fernet key that encrypts face templates | generated into `instance/face_key.txt` |
| `DATABASE_URL` | SQLAlchemy URL | SQLite in `instance/` |
| `MATCH_THRESHOLD` | Auto-mark at or below this distance | `0.5` |
| `REVIEW_THRESHOLD` | Teacher review up to this distance | `0.6` |
| `LATE_AFTER` | Check-ins after this time are "Late" | `09:15` |
| `SCHOOL_NAME` | Shown in the UI | `Your School` |
| `SESSION_COOKIE_SECURE` | Set `1` when serving over HTTPS | `0` |

Back up `FACE_ENCRYPTION_KEY` separately. Without it, enrolled face templates cannot be decrypted and must be re-captured. Store it in a secrets manager, not in the repository.

## 6. Testing
```bash
pytest -q test_flow.py
```
The tests cover login and role checks, consent gating, encrypted enrolment, verification, duplicate prevention, uncertain-match review, manual marking, CSV and Excel export (including formula-injection protection), deletion, and consent withdrawal. Face *detection* is replaced by a stub in these tests, so they do not need dlib. Test the camera path manually with real faces (see checklist below).

### Manual test checklist
1. Start the camera on the Take attendance page. Deny permission and confirm the message appears.
2. Enrol a consenting volunteer with a photo at roughly arm's length. Confirm the profile shows "Enrolled".
3. Face the camera: a green "Attendance Marked Successfully" card appears, and the row appears in "Marked today".
4. Stay in frame: the next result is "Already marked today" and no duplicate row is created.
5. Show an unenrolled person: "Unknown Student".
6. Export CSV and Excel from Records for today, and confirm absent students are listed.

## Data protection and privacy
- Photos are processed in memory and discarded. The database stores a Fernet-encrypted 128-number vector per student.
- Consent is recorded per student with a timestamp. Unchecking consent removes the face template immediately. Deleting a student removes attendance and face data.
- Under-18 students require a parental consent flag before enrolment. Check your local law as well: for example, India's Digital Personal Data Protection Act 2023 requires verifiable parental consent for children under 18.
- Set a retention policy for attendance and audit records. Deleting a student is the only automatic removal path.

## Known limitations (read before deploying)
- **No liveness detection.** A printed photo or phone screen held to the camera may be accepted. Mitigate with supervised check-in, or add a liveness model before relying on the system for anything consequential.
- **Accuracy depends on conditions.** Use even front lighting, enrol in the same setting students will check in, and tune `MATCH_THRESHOLD` and `REVIEW_THRESHOLD` on your own data.
- **Scale.** Every scan compares against all enrolled templates in memory. This is fine for a few thousand students per campus. Beyond that, add a vector index.
- **Single-server design.** Use MySQL and a WSGI server (for example `gunicorn -w 2 "app:create_app()"`) for multi-user deployments. SQLite serialises writes.
- Attendance percentage is based on days when attendance was taken for the school.
