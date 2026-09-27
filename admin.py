"""Admin blueprint — full portal management."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import get_db, parse_dt
from auth import login_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@login_required("admin")
def dashboard():
    db = get_db()
    stats = {
        "courses": db.execute("SELECT COUNT(*) c FROM courses").fetchone()["c"],
        "examinations": db.execute("SELECT COUNT(*) c FROM examinations").fetchone()["c"],
        "examiners": db.execute(
            "SELECT COUNT(*) c FROM users WHERE role='examiner' AND status='approved'"
        ).fetchone()["c"],
        "examiners_pending": db.execute(
            "SELECT COUNT(*) c FROM users WHERE role='examiner' AND status='pending'"
        ).fetchone()["c"],
        "students": db.execute(
            "SELECT COUNT(*) c FROM users WHERE role='student'"
        ).fetchone()["c"],
        "slots": db.execute("SELECT COUNT(*) c FROM slots").fetchone()["c"],
        "bookings": db.execute(
            "SELECT COUNT(*) c FROM bookings WHERE status='Booked'"
        ).fetchone()["c"],
    }
    recent_bookings = db.execute(
        """SELECT b.id, b.booking_date, b.status,
                  u.name AS student_name, s.slot_date, s.start_time,
                  e.name AS exam_name
             FROM bookings b
             JOIN users u ON u.id = b.student_id
             JOIN slots s ON s.id = b.slot_id
             JOIN examinations e ON e.id = s.examination_id
            ORDER BY b.booking_date DESC LIMIT 10"""
    ).fetchall()
    return render_template("admin/dashboard.html", stats=stats, recent=recent_bookings)


# ---------- Courses ----------

@bp.route("/courses")
@login_required("admin")
def courses():
    q = request.args.get("q", "").strip()
    db = get_db()
    if q:
        rows = db.execute(
            "SELECT * FROM courses WHERE code LIKE ? OR name LIKE ? ORDER BY id DESC",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM courses ORDER BY id DESC").fetchall()
    return render_template("admin/courses.html", courses=rows, q=q)


@bp.route("/courses/new", methods=("GET", "POST"))
@bp.route("/courses/<int:course_id>/edit", methods=("GET", "POST"))
@login_required("admin")
def course_form(course_id=None):
    db = get_db()
    course = None
    if course_id:
        course = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        if not course:
            flash("Course not found.", "danger")
            return redirect(url_for("admin.courses"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        status = request.form.get("status", "active")
        errors = []
        if not code:
            errors.append("Course code required.")
        if not name:
            errors.append("Course name required.")
        if status not in ("active", "inactive"):
            errors.append("Invalid status.")

        if not errors:
            dup = db.execute(
                "SELECT id FROM courses WHERE code = ? AND id != COALESCE(?, -1)",
                (code, course_id),
            ).fetchone()
            if dup:
                errors.append("Course code already in use.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            if course_id:
                db.execute(
                    "UPDATE courses SET code=?, name=?, description=?, status=? WHERE id=?",
                    (code, name, description, status, course_id),
                )
                flash("Course updated.", "success")
            else:
                db.execute(
                    "INSERT INTO courses (code, name, description, status) VALUES (?, ?, ?, ?)",
                    (code, name, description, status),
                )
                flash("Course created.", "success")
            db.commit()
            return redirect(url_for("admin.courses"))

    return render_template("admin/course_form.html", course=course)


@bp.route("/courses/<int:course_id>/delete", methods=("POST",))
@login_required("admin")
def course_delete(course_id):
    db = get_db()
    db.execute("DELETE FROM courses WHERE id = ?", (course_id,))
    db.commit()
    flash("Course removed.", "info")
    return redirect(url_for("admin.courses"))


# ---------- Examinations ----------

@bp.route("/examinations")
@login_required("admin")
def examinations():
    q = request.args.get("q", "").strip()
    db = get_db()
    sql = """SELECT e.*, c.code AS course_code, c.name AS course_name
               FROM examinations e JOIN courses c ON c.id = e.course_id"""
    params = ()
    if q:
        sql += " WHERE e.name LIKE ? OR c.code LIKE ? OR c.name LIKE ?"
        params = (f"%{q}%", f"%{q}%", f"%{q}%")
    sql += " ORDER BY e.id DESC"
    exams = db.execute(sql, params).fetchall()
    return render_template("admin/examinations.html", exams=exams, q=q)


@bp.route("/examinations/new", methods=("GET", "POST"))
@bp.route("/examinations/<int:exam_id>/edit", methods=("GET", "POST"))
@login_required("admin")
def examination_form(exam_id=None):
    db = get_db()
    exam = None
    if exam_id:
        exam = db.execute("SELECT * FROM examinations WHERE id = ?", (exam_id,)).fetchone()
        if not exam:
            flash("Examination not found.", "danger")
            return redirect(url_for("admin.examinations"))

    courses = db.execute(
        "SELECT id, code, name FROM courses WHERE status='active' ORDER BY code"
    ).fetchall()

    if request.method == "POST":
        course_id = request.form.get("course_id", type=int)
        name = request.form.get("name", "").strip()
        exam_type = request.form.get("exam_type", "").strip()
        duration = request.form.get("duration_minutes", type=int)
        max_marks = request.form.get("max_marks", type=int)
        sc_start = request.form.get("slot_create_start") or None
        sc_end = request.form.get("slot_create_end") or None
        sb_start = request.form.get("slot_book_start") or None
        sb_end = request.form.get("slot_book_end") or None
        status = request.form.get("status", "Draft")

        errors = []
        if not course_id:
            errors.append("Course required.")
        if not name:
            errors.append("Examination name required.")
        if exam_type not in ("Viva", "Practical", "Project Demo", "Assessment"):
            errors.append("Invalid examination type.")
        if not duration or duration <= 0:
            errors.append("Valid duration required.")
        if not max_marks or max_marks <= 0:
            errors.append("Valid maximum marks required.")
        if status not in ("Draft", "Slot Creation", "Booking Open", "Closed", "Completed"):
            errors.append("Invalid status.")

        for label, val in (
            ("Slot creation start", sc_start),
            ("Slot creation end", sc_end),
            ("Slot booking start", sb_start),
            ("Slot booking end", sb_end),
        ):
            if val and parse_dt(val) is None:
                errors.append(f"{label} has invalid date/time.")

        if sc_start and sc_end and parse_dt(sc_start) and parse_dt(sc_end):
            if parse_dt(sc_start) >= parse_dt(sc_end):
                errors.append("Slot creation start must be before end.")
        if sb_start and sb_end and parse_dt(sb_start) and parse_dt(sb_end):
            if parse_dt(sb_start) >= parse_dt(sb_end):
                errors.append("Slot booking start must be before end.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            args = (course_id, name, exam_type, duration, max_marks,
                    sc_start, sc_end, sb_start, sb_end, status)
            if exam_id:
                db.execute(
                    """UPDATE examinations SET course_id=?, name=?, exam_type=?,
                        duration_minutes=?, max_marks=?, slot_create_start=?,
                        slot_create_end=?, slot_book_start=?, slot_book_end=?, status=?
                        WHERE id=?""",
                    args + (exam_id,),
                )
                flash("Examination updated.", "success")
            else:
                db.execute(
                    """INSERT INTO examinations
                        (course_id, name, exam_type, duration_minutes, max_marks,
                         slot_create_start, slot_create_end, slot_book_start,
                         slot_book_end, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    args,
                )
                flash("Examination created.", "success")
            db.commit()
            return redirect(url_for("admin.examinations"))

    return render_template("admin/examination_form.html", exam=exam, courses=courses)


@bp.route("/examinations/<int:exam_id>/delete", methods=("POST",))
@login_required("admin")
def examination_delete(exam_id):
    db = get_db()
    db.execute("DELETE FROM examinations WHERE id = ?", (exam_id,))
    db.commit()
    flash("Examination removed.", "info")
    return redirect(url_for("admin.examinations"))


@bp.route("/examinations/<int:exam_id>/toggle-slot-creation", methods=("POST",))
@login_required("admin")
def toggle_slot_creation(exam_id):
    db = get_db()
    exam = db.execute("SELECT * FROM examinations WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        flash("Examination not found.", "danger")
        return redirect(url_for("admin.examinations"))
    new_status = "Slot Creation" if exam["status"] != "Slot Creation" else "Draft"
    db.execute("UPDATE examinations SET status = ? WHERE id = ?", (new_status, exam_id))
    db.commit()
    flash(f"Examination status set to '{new_status}'.", "info")
    return redirect(url_for("admin.examinations"))


@bp.route("/examinations/<int:exam_id>/toggle-booking", methods=("POST",))
@login_required("admin")
def toggle_booking(exam_id):
    db = get_db()
    exam = db.execute("SELECT * FROM examinations WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        flash("Examination not found.", "danger")
        return redirect(url_for("admin.examinations"))
    new_status = "Booking Open" if exam["status"] != "Booking Open" else "Closed"
    db.execute("UPDATE examinations SET status = ? WHERE id = ?", (new_status, exam_id))
    db.commit()
    flash(f"Examination status set to '{new_status}'.", "info")
    return redirect(url_for("admin.examinations"))


@bp.route("/examinations/<int:exam_id>/publish-results", methods=("POST",))
@login_required("admin")
def publish_results(exam_id):
    db = get_db()
    db.execute("UPDATE examinations SET results_published = 1 WHERE id = ?", (exam_id,))
    db.commit()
    flash("Results published to students.", "success")
    return redirect(url_for("admin.examinations"))


# ---------- Rubrics ----------

@bp.route("/examinations/<int:exam_id>/rubrics")
@login_required("admin")
def rubrics(exam_id):
    db = get_db()
    exam = db.execute("SELECT * FROM examinations WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        flash("Examination not found.", "danger")
        return redirect(url_for("admin.examinations"))
    items = db.execute(
        "SELECT * FROM rubrics WHERE examination_id = ? ORDER BY id",
        (exam_id,),
    ).fetchall()
    return render_template("admin/rubrics.html", exam=exam, rubrics=items)


@bp.route("/examinations/<int:exam_id>/rubrics/new", methods=("GET", "POST"))
@bp.route("/rubrics/<int:rubric_id>/edit", methods=("GET", "POST"))
@login_required("admin")
def rubric_form(exam_id=None, rubric_id=None):
    db = get_db()
    rubric = None
    if rubric_id:
        rubric = db.execute("SELECT * FROM rubrics WHERE id = ?", (rubric_id,)).fetchone()
        if not rubric:
            flash("Rubric not found.", "danger")
            return redirect(url_for("admin.examinations"))
        exam_id = rubric["examination_id"]

    exam = db.execute("SELECT * FROM examinations WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        flash("Examination not found.", "danger")
        return redirect(url_for("admin.examinations"))

    if request.method == "POST":
        criterion = request.form.get("criterion", "").strip()
        max_marks = request.form.get("max_marks", type=int)
        weightage = request.form.get("weightage", type=float)
        description = request.form.get("description", "").strip()

        errors = []
        if not criterion:
            errors.append("Criterion required.")
        if not max_marks or max_marks <= 0:
            errors.append("Valid maximum marks required.")
        if weightage is None or weightage <= 0:
            errors.append("Valid weightage required.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            if rubric_id:
                db.execute(
                    "UPDATE rubrics SET criterion=?, max_marks=?, weightage=?, description=? WHERE id=?",
                    (criterion, max_marks, weightage, description, rubric_id),
                )
                flash("Rubric updated.", "success")
            else:
                db.execute(
                    """INSERT INTO rubrics
                        (examination_id, criterion, max_marks, weightage, description)
                        VALUES (?, ?, ?, ?, ?)""",
                    (exam_id, criterion, max_marks, weightage, description),
                )
                flash("Rubric added.", "success")
            db.commit()
            return redirect(url_for("admin.rubrics", exam_id=exam_id))

    return render_template("admin/rubric_form.html", exam=exam, rubric=rubric)


@bp.route("/rubrics/<int:rubric_id>/delete", methods=("POST",))
@login_required("admin")
def rubric_delete(rubric_id):
    db = get_db()
    row = db.execute("SELECT examination_id FROM rubrics WHERE id = ?", (rubric_id,)).fetchone()
    if not row:
        return redirect(url_for("admin.examinations"))
    db.execute("DELETE FROM rubrics WHERE id = ?", (rubric_id,))
    db.commit()
    flash("Rubric removed.", "info")
    return redirect(url_for("admin.rubrics", exam_id=row["examination_id"]))


# ---------- Examiners ----------

@bp.route("/examiners")
@login_required("admin")
def examiners():
    q = request.args.get("q", "").strip()
    db = get_db()
    sql = "SELECT * FROM users WHERE role='examiner'"
    params = ()
    if q:
        sql += " AND (name LIKE ? OR username LIKE ? OR email LIKE ?)"
        params = (f"%{q}%", f"%{q}%", f"%{q}%")
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, params).fetchall()
    return render_template("admin/examiners.html", examiners=rows, q=q)


@bp.route("/examiners/<int:examiner_id>/approve", methods=("POST",))
@login_required("admin")
def examiner_approve(examiner_id):
    db = get_db()
    db.execute(
        "UPDATE users SET status='approved' WHERE id=? AND role='examiner'",
        (examiner_id,),
    )
    db.commit()
    flash("Examiner approved.", "success")
    return redirect(url_for("admin.examiners"))


@bp.route("/examiners/<int:examiner_id>/deactivate", methods=("POST",))
@login_required("admin")
def examiner_deactivate(examiner_id):
    db = get_db()
    db.execute(
        "UPDATE users SET status='deactivated' WHERE id=? AND role='examiner'",
        (examiner_id,),
    )
    db.commit()
    flash("Examiner deactivated.", "info")
    return redirect(url_for("admin.examiners"))


@bp.route("/examiners/<int:examiner_id>/reactivate", methods=("POST",))
@login_required("admin")
def examiner_reactivate(examiner_id):
    db = get_db()
    db.execute(
        "UPDATE users SET status='approved' WHERE id=? AND role='examiner'",
        (examiner_id,),
    )
    db.commit()
    flash("Examiner reactivated.", "success")
    return redirect(url_for("admin.examiners"))


# ---------- Students ----------

@bp.route("/students")
@login_required("admin")
def students():
    q = request.args.get("q", "").strip()
    db = get_db()
    sql = "SELECT * FROM users WHERE role='student'"
    params = ()
    if q:
        sql += " AND (name LIKE ? OR username LIKE ? OR email LIKE ?)"
        params = (f"%{q}%", f"%{q}%", f"%{q}%")
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, params).fetchall()
    return render_template("admin/students.html", students=rows, q=q)


# ---------- Slots ----------

@bp.route("/slots")
@login_required("admin")
def slots():
    db = get_db()
    rows = db.execute(
        """SELECT s.*, e.name AS exam_name, c.code AS course_code,
                  u.name AS examiner_name,
                  (SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id AND b.status='Booked') AS booked
             FROM slots s
             JOIN examinations e ON e.id = s.examination_id
             JOIN courses c ON c.id = e.course_id
             JOIN users u ON u.id = s.examiner_id
            ORDER BY s.slot_date DESC, s.start_time DESC"""
    ).fetchall()
    return render_template("admin/slots.html", slots=rows)


@bp.route("/slots/<int:slot_id>/change-examiner", methods=("GET", "POST"))
@login_required("admin")
def change_examiner(slot_id):
    db = get_db()
    slot = db.execute(
        """SELECT s.*, e.name AS exam_name
             FROM slots s
             JOIN examinations e ON e.id = s.examination_id
            WHERE s.id = ?""",
        (slot_id,),
    ).fetchone()
    if not slot:
        flash("Slot not found.", "danger")
        return redirect(url_for("admin.slots"))

    examiners = db.execute(
        "SELECT id, name FROM users WHERE role='examiner' AND status='approved' ORDER BY name"
    ).fetchall()

    if request.method == "POST":
        new_examiner_id = request.form.get("examiner_id", type=int)
        if not new_examiner_id:
            flash("Select an examiner.", "danger")
        else:
            db.execute(
                "UPDATE slots SET examiner_id = ? WHERE id = ?",
                (new_examiner_id, slot_id),
            )
            db.commit()
            flash("Examiner reassigned.", "success")
            return redirect(url_for("admin.slots"))

    return render_template("admin/change_examiner.html", slot=slot, examiners=examiners)


# ---------- Bookings ----------

@bp.route("/bookings")
@login_required("admin")
def bookings():
    q = request.args.get("q", "").strip()
    db = get_db()
    sql = """SELECT b.*, u.name AS student_name, u.username AS student_username,
                    s.slot_date, s.start_time, s.end_time,
                    e.name AS exam_name, c.code AS course_code,
                    ex.name AS examiner_name
               FROM bookings b
               JOIN users u ON u.id = b.student_id
               JOIN slots s ON s.id = b.slot_id
               JOIN examinations e ON e.id = s.examination_id
               JOIN courses c ON c.id = e.course_id
               JOIN users ex ON ex.id = s.examiner_id"""
    params = ()
    if q:
        sql += " WHERE u.name LIKE ? OR u.username LIKE ? OR e.name LIKE ?"
        params = (f"%{q}%", f"%{q}%", f"%{q}%")
    sql += " ORDER BY b.booking_date DESC"
    rows = db.execute(sql, params).fetchall()
    return render_template("admin/bookings.html", bookings=rows, q=q)


@bp.route("/bookings/<int:booking_id>/reschedule", methods=("GET", "POST"))
@login_required("admin")
def reschedule(booking_id):
    db = get_db()
    booking = db.execute(
        """SELECT b.*, s.examination_id, s.slot_date, s.start_time,
                  e.name AS exam_name, u.name AS student_name
             FROM bookings b
             JOIN slots s ON s.id = b.slot_id
             JOIN examinations e ON e.id = s.examination_id
             JOIN users u ON u.id = b.student_id
            WHERE b.id = ?""",
        (booking_id,),
    ).fetchone()
    if not booking:
        flash("Booking not found.", "danger")
        return redirect(url_for("admin.bookings"))

    available_slots = db.execute(
        """SELECT s.*, u.name AS examiner_name,
                  (SELECT COUNT(*) FROM bookings b2 WHERE b2.slot_id = s.id AND b2.status='Booked') AS booked
             FROM slots s
             JOIN users u ON u.id = s.examiner_id
            WHERE s.examination_id = ? AND s.status IN ('Available','Full')
              AND s.id != ?
            ORDER BY s.slot_date, s.start_time""",
        (booking["examination_id"], booking["slot_id"]),
    ).fetchall()

    if request.method == "POST":
        new_slot_id = request.form.get("slot_id", type=int)
        if not new_slot_id:
            flash("Choose a slot.", "danger")
        else:
            new_slot = db.execute("SELECT * FROM slots WHERE id = ?", (new_slot_id,)).fetchone()
            booked = db.execute(
                "SELECT COUNT(*) c FROM bookings WHERE slot_id=? AND status='Booked'",
                (new_slot_id,),
            ).fetchone()["c"]
            if booked >= new_slot["max_capacity"]:
                flash("Selected slot is at capacity.", "danger")
            else:
                db.execute(
                    "UPDATE bookings SET slot_id = ? WHERE id = ?",
                    (new_slot_id, booking_id),
                )
                db.commit()
                flash("Booking rescheduled.", "success")
                return redirect(url_for("admin.bookings"))

    return render_template(
        "admin/reschedule.html", booking=booking, slots=available_slots
    )
