"""Examiner blueprint — slot creation, evaluation, marks submission."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime

from models import get_db, parse_dt, in_window
from auth import login_required

bp = Blueprint("examiner", __name__, url_prefix="/examiner")


def _me():
    return session["user"]["id"]


@bp.route("/")
@login_required("examiner")
def dashboard():
    db = get_db()
    me = _me()

    stats = {
        "slots": db.execute(
            "SELECT COUNT(*) c FROM slots WHERE examiner_id = ?", (me,)
        ).fetchone()["c"],
        "assigned_exams": db.execute(
            "SELECT COUNT(DISTINCT examination_id) c FROM slots WHERE examiner_id = ?",
            (me,),
        ).fetchone()["c"],
        "students_booked": db.execute(
            """SELECT COUNT(*) c FROM bookings b
                JOIN slots s ON s.id = b.slot_id
               WHERE s.examiner_id = ? AND b.status = 'Booked'""",
            (me,),
        ).fetchone()["c"],
        "pending_evals": db.execute(
            """SELECT COUNT(*) c FROM bookings b
                JOIN slots s ON s.id = b.slot_id
               WHERE s.examiner_id = ? AND b.status IN ('Booked','Completed')
                 AND NOT EXISTS (
                    SELECT 1 FROM evaluation_summary es WHERE es.booking_id = b.id
                 )""",
            (me,),
        ).fetchone()["c"],
    }

    assigned = db.execute(
        """SELECT DISTINCT e.id, e.name, e.exam_type, e.status, c.code AS course_code
             FROM slots s
             JOIN examinations e ON e.id = s.examination_id
             JOIN courses c ON c.id = e.course_id
            WHERE s.examiner_id = ?
            ORDER BY e.id DESC""",
        (me,),
    ).fetchall()

    return render_template(
        "examiner/dashboard.html", stats=stats, assigned=assigned
    )


@bp.route("/slots")
@login_required("examiner")
def slots():
    db = get_db()
    me = _me()
    rows = db.execute(
        """SELECT s.*, e.name AS exam_name, c.code AS course_code,
                  (SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id AND b.status='Booked') AS booked
             FROM slots s
             JOIN examinations e ON e.id = s.examination_id
             JOIN courses c ON c.id = e.course_id
            WHERE s.examiner_id = ?
            ORDER BY s.slot_date DESC, s.start_time DESC""",
        (me,),
    ).fetchall()
    return render_template("examiner/slots.html", slots=rows)


@bp.route("/slots/new", methods=("GET", "POST"))
@bp.route("/slots/<int:slot_id>/edit", methods=("GET", "POST"))
@login_required("examiner")
def slot_form(slot_id=None):
    db = get_db()
    me = _me()
    slot = None
    if slot_id:
        slot = db.execute(
            "SELECT * FROM slots WHERE id = ? AND examiner_id = ?", (slot_id, me)
        ).fetchone()
        if not slot:
            flash("Slot not found.", "danger")
            return redirect(url_for("examiner.slots"))
        booked_count = db.execute(
            "SELECT COUNT(*) c FROM bookings WHERE slot_id=? AND status='Booked'",
            (slot_id,),
        ).fetchone()["c"]
        if booked_count > 0:
            flash("Cannot edit a slot that already has bookings.", "warning")
            return redirect(url_for("examiner.slots"))

    exams = db.execute(
        "SELECT id, name FROM examinations WHERE status = 'Slot Creation' ORDER BY id DESC"
    ).fetchall()

    if request.method == "POST":
        exam_id = request.form.get("examination_id", type=int)
        slot_date = request.form.get("slot_date", "").strip()
        start_time = request.form.get("start_time", "").strip()
        end_time = request.form.get("end_time", "").strip()
        max_capacity = request.form.get("max_capacity", type=int)

        errors = []
        exam = None
        if not exam_id:
            errors.append("Examination required.")
        else:
            exam = db.execute("SELECT * FROM examinations WHERE id = ?", (exam_id,)).fetchone()
            if not exam:
                errors.append("Examination not found.")
            elif exam["status"] != "Slot Creation":
                errors.append("Slot creation is not open for this examination.")
            else:
                if exam["slot_create_start"] and exam["slot_create_end"]:
                    if not in_window(exam["slot_create_start"], exam["slot_create_end"]):
                        errors.append("Slot creation window is outside allowed dates.")

        if not slot_date:
            errors.append("Date required.")
        if not start_time or not end_time:
            errors.append("Start and end time required.")
        elif start_time >= end_time:
            errors.append("Start time must be before end time.")
        if not max_capacity or max_capacity <= 0:
            errors.append("Valid capacity required.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            if slot_id:
                db.execute(
                    """UPDATE slots SET examination_id=?, slot_date=?, start_time=?,
                        end_time=?, max_capacity=? WHERE id=? AND examiner_id=?""",
                    (exam_id, slot_date, start_time, end_time, max_capacity,
                     slot_id, me),
                )
                flash("Slot updated.", "success")
            else:
                db.execute(
                    """INSERT INTO slots (examination_id, examiner_id, slot_date,
                                          start_time, end_time, max_capacity, status)
                       VALUES (?, ?, ?, ?, ?, ?, 'Available')""",
                    (exam_id, me, slot_date, start_time, end_time, max_capacity),
                )
                flash("Slot created.", "success")
            db.commit()
            return redirect(url_for("examiner.slots"))

    return render_template("examiner/slot_form.html", slot=slot, exams=exams)


@bp.route("/slots/<int:slot_id>/delete", methods=("POST",))
@login_required("examiner")
def slot_delete(slot_id):
    db = get_db()
    me = _me()
    booked = db.execute(
        "SELECT COUNT(*) c FROM bookings WHERE slot_id=? AND status='Booked'",
        (slot_id,),
    ).fetchone()["c"]
    if booked > 0:
        flash("Cannot delete a slot with active bookings.", "danger")
        return redirect(url_for("examiner.slots"))
    db.execute(
        "DELETE FROM slots WHERE id = ? AND examiner_id = ?", (slot_id, me)
    )
    db.commit()
    flash("Slot removed.", "info")
    return redirect(url_for("examiner.slots"))


@bp.route("/slots/<int:slot_id>/booked")
@login_required("examiner")
def booked_students(slot_id):
    db = get_db()
    me = _me()
    slot = db.execute(
        """SELECT s.*, e.name AS exam_name, c.code AS course_code
             FROM slots s
             JOIN examinations e ON e.id = s.examination_id
             JOIN courses c ON c.id = e.course_id
            WHERE s.id = ? AND s.examiner_id = ?""",
        (slot_id, me),
    ).fetchone()
    if not slot:
        flash("Slot not found.", "danger")
        return redirect(url_for("examiner.slots"))

    rows = db.execute(
        """SELECT b.id AS booking_id, b.status AS booking_status,
                  u.id AS student_id, u.name AS student_name, u.username,
                  (SELECT total_marks FROM evaluation_summary WHERE booking_id = b.id) AS total
             FROM bookings b
             JOIN users u ON u.id = b.student_id
            WHERE b.slot_id = ?
            ORDER BY u.name""",
        (slot_id,),
    ).fetchall()
    return render_template(
        "examiner/booked_students.html", slot=slot, bookings=rows
    )


@bp.route("/bookings/<int:booking_id>/evaluate", methods=("GET", "POST"))
@login_required("examiner")
def evaluate(booking_id):
    db = get_db()
    me = _me()

    booking = db.execute(
        """SELECT b.*, s.examination_id, s.examiner_id, u.name AS student_name,
                  e.name AS exam_name, e.max_marks
             FROM bookings b
             JOIN slots s ON s.id = b.slot_id
             JOIN users u ON u.id = b.student_id
             JOIN examinations e ON e.id = s.examination_id
            WHERE b.id = ?""",
        (booking_id,),
    ).fetchone()
    if not booking:
        flash("Booking not found.", "danger")
        return redirect(url_for("examiner.dashboard"))
    if booking["examiner_id"] != me:
        flash("You can only evaluate students booked into your own slots.", "danger")
        return redirect(url_for("examiner.dashboard"))

    rubrics = db.execute(
        "SELECT * FROM rubrics WHERE examination_id = ? ORDER BY id",
        (booking["examination_id"],),
    ).fetchall()

    existing = {
        r["rubric_id"]: r
        for r in db.execute(
            "SELECT * FROM evaluations WHERE booking_id = ?", (booking_id,)
        ).fetchall()
    }
    summary = db.execute(
        "SELECT * FROM evaluation_summary WHERE booking_id = ?", (booking_id,)
    ).fetchone()

    if request.method == "POST":
        errors = []
        marks_map = {}
        remarks_map = {}
        for r in rubrics:
            raw = request.form.get(f"marks_{r['id']}", "").strip()
            rem = request.form.get(f"remarks_{r['id']}", "").strip()
            try:
                m = float(raw)
            except (TypeError, ValueError):
                errors.append(f"Invalid marks for '{r['criterion']}'.")
                continue
            if m < 0 or m > r["max_marks"]:
                errors.append(
                    f"Marks for '{r['criterion']}' must be between 0 and {r['max_marks']}."
                )
                continue
            marks_map[r["id"]] = m
            remarks_map[r["id"]] = rem
        overall = request.form.get("overall_remarks", "").strip()

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            total = 0.0
            for r in rubrics:
                m = marks_map[r["id"]]
                rem = remarks_map[r["id"]]
                total += m * (r["weightage"] or 1.0)
                if r["id"] in existing:
                    db.execute(
                        "UPDATE evaluations SET marks=?, remarks=? WHERE id=?",
                        (m, rem, existing[r["id"]]["id"]),
                    )
                else:
                    db.execute(
                        """INSERT INTO evaluations
                            (booking_id, rubric_id, marks, remarks)
                            VALUES (?, ?, ?, ?)""",
                        (booking_id, r["id"], m, rem),
                    )
            if summary:
                db.execute(
                    """UPDATE evaluation_summary SET total_marks=?, overall_remarks=?,
                        evaluated_at=datetime('now') WHERE booking_id=?""",
                    (total, overall, booking_id),
                )
            else:
                db.execute(
                    """INSERT INTO evaluation_summary
                        (booking_id, total_marks, overall_remarks)
                        VALUES (?, ?, ?)""",
                    (booking_id, total, overall),
                )
            db.execute(
                "UPDATE bookings SET status='Completed' WHERE id = ?", (booking_id,)
            )
            db.commit()
            flash("Evaluation saved.", "success")
            return redirect(url_for("examiner.booked_students", slot_id=booking["slot_id"]))

    return render_template(
        "examiner/evaluate.html",
        booking=booking,
        rubrics=rubrics,
        existing=existing,
        summary=summary,
    )
