"""Authentication: login, logout, registration for examiners and students."""
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from models import get_db

bp = Blueprint("auth", __name__)


def login_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = session.get("user")
            if not user:
                flash("Please log in.", "warning")
                return redirect(url_for("auth.login"))
            if roles and user["role"] not in roles:
                flash("You do not have access to this page.", "danger")
                return redirect(url_for("index"))
            if user["role"] == "examiner" and user.get("status") != "approved":
                flash("Your examiner account is awaiting Admin approval.", "warning")
                session.pop("user", None)
                return redirect(url_for("auth.login"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        row = db.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?",
            (username, username),
        ).fetchone()

        if not row or not check_password_hash(row["password_hash"], password):
            flash("Invalid username or password.", "danger")
            return render_template("auth/login.html", username=username)

        if row["role"] == "examiner" and row["status"] != "approved":
            flash(
                f"Examiner account status is '{row['status']}'. "
                "Wait for Admin approval or contact Admin.",
                "warning",
            )
            return render_template("auth/login.html", username=username)

        if row["status"] == "deactivated":
            flash("Your account has been deactivated. Contact Admin.", "danger")
            return render_template("auth/login.html", username=username)

        session.clear()
        session["user"] = {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "name": row["name"],
            "status": row["status"],
        }
        flash(f"Welcome, {row['name']}.", "success")
        return redirect(url_for(f"{row['role']}.dashboard"))

    return render_template("auth/login.html")


@bp.route("/register", methods=("GET", "POST"))
def register():
    role = request.args.get("role", "student")
    if role not in ("student", "examiner"):
        role = "student"

    if request.method == "POST":
        role = request.form.get("role", "student")
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        contact = request.form.get("contact", "").strip()
        department = request.form.get("department", "").strip()

        errors = []
        if role not in ("student", "examiner"):
            errors.append("Invalid role.")
        if not username or len(username) < 3:
            errors.append("Username must be at least 3 characters.")
        if not email or "@" not in email:
            errors.append("Valid email required.")
        if not name:
            errors.append("Name required.")
        if not password or len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        db = get_db()
        if not errors:
            existing = db.execute(
                "SELECT id FROM users WHERE username = ? OR email = ?",
                (username, email),
            ).fetchone()
            if existing:
                errors.append("Username or email already registered.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "auth/register.html",
                role=role,
                username=username,
                email=email,
                name=name,
                contact=contact,
                department=department,
            )

        status = "pending" if role == "examiner" else "active"
        db.execute(
            """INSERT INTO users
               (username, email, password_hash, role, name, contact, department, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (username, email, generate_password_hash(password), role,
             name, contact or None, department or None, status),
        )
        db.commit()

        if role == "examiner":
            flash(
                "Registration successful. Your examiner account is pending Admin approval.",
                "info",
            )
        else:
            flash("Registration successful. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", role=role)


@bp.route("/logout")
def logout():
    session.pop("user", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
