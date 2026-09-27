"""Database schema, connection helpers, and programmatic initialisation."""
import sqlite3
from datetime import datetime
from flask import g, current_app
from werkzeug.security import generate_password_hash


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'examiner', 'student')),
        name TEXT NOT NULL,
        contact TEXT,
        department TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS examinations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        exam_type TEXT NOT NULL CHECK (exam_type IN ('Viva', 'Practical', 'Project Demo', 'Assessment')),
        duration_minutes INTEGER NOT NULL,
        max_marks INTEGER NOT NULL,
        slot_create_start TEXT,
        slot_create_end TEXT,
        slot_book_start TEXT,
        slot_book_end TEXT,
        status TEXT NOT NULL DEFAULT 'Draft'
            CHECK (status IN ('Draft', 'Slot Creation', 'Booking Open', 'Closed', 'Completed')),
        results_published INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rubrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        examination_id INTEGER NOT NULL REFERENCES examinations(id) ON DELETE CASCADE,
        criterion TEXT NOT NULL,
        max_marks INTEGER NOT NULL,
        weightage REAL NOT NULL DEFAULT 1.0,
        description TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        examination_id INTEGER NOT NULL REFERENCES examinations(id) ON DELETE CASCADE,
        examiner_id INTEGER NOT NULL REFERENCES users(id),
        slot_date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        max_capacity INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'Available'
            CHECK (status IN ('Available', 'Full', 'Cancelled', 'Completed')),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL REFERENCES users(id),
        slot_id INTEGER NOT NULL REFERENCES slots(id) ON DELETE CASCADE,
        booking_date TEXT NOT NULL DEFAULT (datetime('now')),
        status TEXT NOT NULL DEFAULT 'Booked'
            CHECK (status IN ('Booked', 'Cancelled', 'Completed')),
        UNIQUE(student_id, slot_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
        rubric_id INTEGER NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
        marks REAL NOT NULL,
        remarks TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(booking_id, rubric_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluation_summary (
        booking_id INTEGER PRIMARY KEY REFERENCES bookings(id) ON DELETE CASCADE,
        total_marks REAL NOT NULL,
        overall_remarks TEXT,
        evaluated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
]


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    with app.app_context():
        db = get_db()
        for stmt in SCHEMA:
            db.execute(stmt)
        db.commit()
        _seed_admin(db, app)


def _seed_admin(db, app):
    cur = db.execute("SELECT id FROM users WHERE role = 'admin'")
    if cur.fetchone() is None:
        db.execute(
            """INSERT INTO users (username, email, password_hash, role, name, status)
               VALUES (?, ?, ?, 'admin', ?, 'active')""",
            (
                app.config["ADMIN_USERNAME"],
                app.config["ADMIN_EMAIL"],
                generate_password_hash(app.config["ADMIN_PASSWORD"]),
                app.config["ADMIN_NAME"],
            ),
        )
        db.commit()


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def in_window(start_iso, end_iso, now=None):
    if not start_iso or not end_iso:
        return False
    now = now or datetime.now()
    start = parse_dt(start_iso)
    end = parse_dt(end_iso)
    if not start or not end:
        return False
    return start <= now <= end
