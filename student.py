"""Student blueprint — browse examinations, book/cancel slots, view results."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime

from models import get_db, in_window
from auth import login_required
from werkzeug.security import generate_password_hash, check_password_hash

bp = Blueprint("student", __name__, url_prefix="/student")


def _me():
    return session["user"]["id"]


@bp.route("/")
@login_required("student")
def dashboard():
    db = get_db()
    me = _me()

    available_exams = db.execute(
        """SELECT e.*, c.code AS course_code, c.name AS course_name
             FROM examinations e JOIN courses c ON c.id = e.course_id
            WHERE e.status = 'Booking Open'
            ORDER BY e.id DESC"""
    ).fetchall()

    my_bookings = db.execute(
        """SELECT b.*, s.slot_date, s.start_time, s.end_time,
                  e.name AS exam_name, e.results_published,
                  c.code AS course_code, u.name AS examiner_name,
                  (SELECT total_marks FROM evaluation_summary WHERE booking_id = b.id) AS total
             FROM bookings b
             JOIN slots s ON s.id = b.slot_id
             JOIN examinations e ON e.id = s.examination_id
             JOIN courses c ON c.id = e.course_id
             JOIN users u ON u.id = s.examiner_id
            WHERE b.student_id = ?
            ORDER BY b.booking_date DESC""",
        (me,),
    ).fetchall()

    stats = {
        "available_exams": len(available_exams),
        "active_bookings": sum(1 for b in my_bookings if b["status"] == "Booked"),
        "completed": sum(1 for b in my_bookings if b["status"] == "Completed"),
    }
    return render_template(
        "student/dashboard.html",
        available_exams=available_exams,
        my_bookings=my_bookings,
        stats=stats,
    )


@bp.route("/examinations")
@login_required("student")
def examinations():
    q = request.args.get("q", "").strip()
    exam_type = request.args.get("type", "").strip()
    db = get_db()

    sql = """SELECT e.*, c.code AS course_code, c.name AS course_name
               FROM examinations e JOIN courses c ON c.id = e.course_id
              WHERE e.status = 'Booking Open'"""
    params = []
    if q:
        sql += " AND (e.name LIKE ? OR c.code LIKE ? OR c.name LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if exam_type:
        sql += " AND e.exam_type = ?"
        params.append(exam_type)
    sql += " ORDER BY e.id DESC"

    exams = db.execute(sql, params).fetchall()
    return render_template(
        "student/examinations.html", exams=exams, q=q, exam_type=exam_type
    )


@bp.route("/examinations/<int:exam_id>/slots")
@login_required("student")
def slots(exam_id):
    db = get_db()
    me = _me()
    exam = db.execute(
        """SELECT e.*, c.code AS course_code, c.name AS course_name
             FROM examinations e JOIN courses c ON c.id = e.course_id
            WHERE e.id = ?""",
        (exam_id,),
    ).fetchone()
    if not exam:
        flash("Examination not found.", "danger")
        return redirect(url_for("student.examinations"))

    open_for_booking = (
        exam["status"] == "Booking Open"
        and (
            not (exam["slot_book_start"] and exam["slot_book_end"])
            or in_window(exam["slot_book_start"], exam["slot_book_end"])
        )
    )

    slot_rows = db.execute(
        """SELECT s.*, u.name AS examiner_name,
                  (SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id AND b.status='Booked') AS booked
             FROM slots s
             JOIN users u ON u.id = s.examiner_id
            WHERE s.examination_id = ? AND s.status IN ('Available','Full')
            ORDER BY s.slot_date, s.start_time""",
        (exam_id,),
    ).fetchall()

    already_booked = db.execute(
        """SELECT b.id FROM bookings b
             JOIN slots s ON s.id = b.slot_id
            WHERE s.examination_id = ? AND b.student_id = ? AND b.status = 'Booked'""",
        (exam_id, me),
    ).fetchone()

    return render_template(
        "student/slots.html",
        exam=exam,
        slots=slot_rows,
        open_for_booking=open_for_booking,
        already_booked=bool(already_booked),
    )


@bp.route("/slots/<int:slot_id>/book", methods=("POST",))
@login_required("student")
def book(slot_id):
    db = get_db()
    me = _me()

    slot = db.execute(
        """SELECT s.*, e.status AS exam_status, e.slot_book_start, e.slot_book_end
             FROM slots s
             JOIN examinations e ON e.id = s.examination_id
            WHERE s.id = ?""",
        (slot_id,),
    ).fetchone()
    if not slot:
        flash("Slot not found.", "danger")
        return redirect(url_for("student.examinations"))

    if slot["exam_status"] != "Booking Open":
        flash("Booking is not open for this examination.", "danger")
        return redirect(url_for("student.slots", exam_id=slot["examination_id"]))

    if slot["slot_book_start"] and slot["slot_book_end"]:
        if not in_window(slot["slot_book_start"], slot["slot_book_end"]):
            flash("Booking window is closed.", "danger")
            return redirect(url_for("student.slots", exam_id=slot["examination_id"]))

    if slot["status"] not in ("Available",):
        flash("This slot is not accepting bookings.", "danger")
        return redirect(url_for("student.slots", exam_id=slot["examination_id"]))

    existing = db.execute(
        """SELECT b.id FROM bookings b
             JOIN slots s ON s.id = b.slot_id
            WHERE s.examination_id = ? AND b.student_id = ? AND b.status = 'Booked'""",
        (slot["examination_id"], me),
    ).fetchone()
    if existing:
        flash("You already have an active booking for this examination.", "warning")
        return redirect(url_for("student.slots", exam_id=slot["examination_id"]))

    booked = db.execute(
        "SELECT COUNT(*) c FROM bookings WHERE slot_id=? AND status='Booked'",
        (slot_id,),
    ).fetchone()["c"]
    if booked >= slot["max_capacity"]:
        db.execute("UPDATE slots SET status='Full' WHERE id = ?", (slot_id,))
        db.commit()
        flash("This slot is now full.", "warning")
        return redirect(url_for("student.slots", exam_id=slot["examination_id"]))

    try:
        db.execute(
            "INSERT INTO bookings (student_id, slot_id, status) VALUES (?, ?, 'Booked')",
            (me, slot_id),
        )
        new_count = booked + 1
        if new_count >= slot["max_capacity"]:
            db.execute("UPDATE slots SET status='Full' WHERE id = ?", (slot_id,))
        db.commit()
        flash("Slot booked successfully.", "success")
    except Exception as exc:
        db.rollback()
        flash(f"Booking failed: {exc}", "danger")

    return redirect(url_for("student.bookings"))


@bp.route("/bookings")
@login_required("student")
def bookings():
    db = get_db()
    me = _me()
    rows = db.execute(
        """SELECT b.*, s.slot_date, s.start_time, s.end_time,
                  e.name AS exam_name, e.exam_type,
                  e.slot_book_end,
                  c.code AS course_code, u.name AS examiner_name,
                  (SELECT total_marks FROM evaluation_summary WHERE booking_id = b.id) AS total
             FROM bookings b
             JOIN slots s ON s.id = b.slot_id
             JOIN examinations e ON e.id = s.examination_id
             JOIN courses c ON c.id = e.course_id
             JOIN users u ON u.id = s.examiner_id
            WHERE b.student_id = ?
            ORDER BY b.booking_date DESC""",
        (me,),
    ).fetchall()
    return render_template("student/bookings.html", bookings=rows)


@bp.route("/bookings/<int:booking_id>/cancel", methods=("POST",))
@login_required("student")
def cancel(booking_id):
    db = get_db()
    me = _me()

    row = db.execute(
        """SELECT b.*, s.max_capacity, e.slot_book_end
             FROM bookings b
             JOIN slots s ON s.id = b.slot_id
             JOIN examinations e ON e.id = s.examination_id
            WHERE b.id = ? AND b.student_id = ?""",
        (booking_id, me),
    ).fetchone()
    if not row:
        flash("Booking not found.", "danger")
        return redirect(url_for("student.bookings"))
    if row["status"] != "Booked":
        flash("Only active bookings can be cancelled.", "warning")
        return redirect(url_for("student.bookings"))

    if row["slot_book_end"]:
        from models import parse_dt
        end = parse_dt(row["slot_book_end"])
        if end and datetime.now() > end:
            flash("Booking deadline has passed. Cancellation not allowed.", "danger")
            return redirect(url_for("student.bookings"))

    db.execute(
        "UPDATE bookings SET status='Cancelled' WHERE id = ?", (booking_id,)
    )
    booked = db.execute(
        "SELECT COUNT(*) c FROM bookings WHERE slot_id=? AND status='Booked'",
        (row["slot_id"],),
    ).fetchone()["c"]
    if booked < row["max_capacity"]:
        db.execute(
            "UPDATE slots SET status='Available' WHERE id = ? AND status = 'Full'",
            (row["slot_id"],),
        )
    db.commit()
    flash("Booking cancelled.", "info")
    return redirect(url_for("student.bookings"))


@bp.route("/results")
@login_required("student")
def results():
    db = get_db()
    me = _me()
    rows = db.execute(
        """SELECT b.id AS booking_id, e.name AS exam_name, e.max_marks,
                  c.code AS course_code, s.slot_date,
                  es.total_marks, es.overall_remarks, es.evaluated_at
             FROM bookings b
             JOIN slots s ON s.id = b.slot_id
             JOIN examinations e ON e.id = s.examination_id
             JOIN courses c ON c.id = e.course_id
             LEFT JOIN evaluation_summary es ON es.booking_id = b.id
            WHERE b.student_id = ?
              AND e.results_published = 1
              AND es.booking_id IS NOT NULL
            ORDER BY es.evaluated_at DESC""",
        (me,),
    ).fetchall()

    breakdowns = {}
    for r in rows:
        breakdowns[r["booking_id"]] = db.execute(
            """SELECT ev.marks, ev.remarks, rb.criterion, rb.max_marks, rb.weightage
                 FROM evaluations ev
                 JOIN rubrics rb ON rb.id = ev.rubric_id
                WHERE ev.booking_id = ?
                ORDER BY rb.id""",
            (r["booking_id"],),
        ).fetchall()

    return render_template("student/results.html", results=rows, breakdowns=breakdowns)


@bp.route("/profile", methods=("GET", "POST"))
@login_required("student")
def profile():
    db = get_db()
    me = _me()
    user = db.execute("SELECT * FROM users WHERE id = ?", (me,)).fetchone()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()
        email = request.form.get("email", "").strip()
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if not name:
            errors.append("Name required.")
        if not email or "@" not in email:
            errors.append("Valid email required.")
        dup = db.execute(
            "SELECT id FROM users WHERE email = ? AND id != ?", (email, me)
        ).fetchone()
        if dup:
            errors.append("Email already in use.")

        change_pw = bool(new_pw or confirm)
        if change_pw:
            if not check_password_hash(user["password_hash"], current_pw):
                errors.append("Current password is incorrect.")
            if len(new_pw) < 6:
                errors.append("New password must be at least 6 characters.")
            if new_pw != confirm:
                errors.append("New passwords do not match.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            if change_pw:
                db.execute(
                    "UPDATE users SET name=?, contact=?, email=?, password_hash=? WHERE id=?",
                    (name, contact or None, email, generate_password_hash(new_pw), me),
                )
            else:
                db.execute(
                    "UPDATE users SET name=?, contact=?, email=? WHERE id=?",
                    (name, contact or None, email, me),
                )
            db.commit()
            session["user"]["name"] = name
            flash("Profile updated.", "success")
            return redirect(url_for("student.profile"))

    return render_template("student/profile.html", user=user)
