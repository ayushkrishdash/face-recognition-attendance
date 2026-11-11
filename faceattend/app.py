import click
from flask import Flask, g
from werkzeug.security import generate_password_hash

import api
import views
from auth import csrf_protect, get_csrf_token, load_logged_in_user
from config import Config
from models import User, db


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    db.init_app(app)
    app.register_blueprint(views.bp)
    app.register_blueprint(api.bp, url_prefix="/api")
    app.before_request(load_logged_in_user)
    app.before_request(csrf_protect)
    app.after_request(_security_headers)
    app.context_processor(lambda: {"csrf_token": get_csrf_token, "school_name": app.config["SCHOOL_NAME"]})

    with app.app_context():
        db.create_all()
    _register_cli(app)
    return app


def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=()")
    if getattr(g, "user", None) is not None:
        response.headers["Cache-Control"] = "no-store"
    return response


def _register_cli(app):
    @app.cli.command("create-user")
    @click.option("--username", required=True)
    @click.option("--name", "full_name", required=True)
    @click.option("--role", type=click.Choice(["admin", "teacher"]), default="teacher", show_default=True)
    @click.password_option()
    def create_user(username, full_name, role, password):
        """Create an admin or teacher account."""
        if len(password) < 10:
            raise click.ClickException("Password must be at least 10 characters.")
        if User.query.filter_by(username=username).first():
            raise click.ClickException("That username already exists.")
        db.session.add(User(username=username, full_name=full_name, role=role,
                            password_hash=generate_password_hash(password)))
        db.session.commit()
        click.echo(f"Created {role} account '{username}'.")


if __name__ == "__main__":
    # Camera access requires a secure context: use localhost, or HTTPS behind a reverse proxy in production.
    create_app().run(host="127.0.0.1", port=5000, debug=False)
