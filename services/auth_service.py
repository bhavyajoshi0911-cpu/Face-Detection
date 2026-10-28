from functools import wraps
from flask import g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from database.database import get_db


def ensure_default_admin():
    db = get_db()
    user = db.execute("SELECT id FROM users LIMIT 1").fetchone()
    if user is None:
        db.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            ("admin", "admin@example.com", generate_password_hash("admin123"), "Admin"),
        )
        db.commit()


def authenticate(username, password):
    user = get_db().execute(
        "SELECT * FROM users WHERE username = ? OR email = ?", (username, username)
    ).fetchone()
    if user and check_password_hash(user["password_hash"], password):
        return user
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return {"success": False, "message": "Authentication required"}, 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "Admin":
            return {"success": False, "message": "Administrator access required"}, 403
        return view(*args, **kwargs)
    return wrapped


def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone() if user_id else None
