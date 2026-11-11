import secrets
from functools import wraps

from flask import g, jsonify, redirect, request, session, url_for, abort

from models import User, db


def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def csrf_protect():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    expected = session.get("csrf_token", "")
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    if expected and sent and secrets.compare_digest(expected, sent):
        return None
    message = "Your session token is missing or expired. Refresh the page and try again."
    if request.path.startswith("/api/"):
        return jsonify(status="error", message=message), 400
    abort(400, description=message)


def load_logged_in_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        user = db.session.get(User, user_id)
        if user and user.is_active:
            g.user = user
        else:
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return jsonify(status="error", message="Please sign in again."), 401
            return redirect(url_for("views.login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if g.user.role not in roles:
                if request.path.startswith("/api/"):
                    return jsonify(status="error", message="You do not have permission for this action."), 403
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator
