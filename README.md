# Examination Management Portal (EMP)

A role-based examination management web application built with:

- **Flask** for the backend
- **Jinja2 + HTML + CSS + Bootstrap 5** for the frontend
- **SQLite** for the database (created programmatically on first run — no manual setup)
- **No JavaScript** for core functionality (only tiny inline `confirm()` prompts on destructive actions)

## Roles

- **Admin** (pre-seeded) — manages courses, examinations, rubrics, examiners, slots, bookings; can reschedule bookings and reassign examiners; opens/closes slot creation and booking windows; publishes results.
- **Examiner** — registers, waits for Admin approval, creates examination slots during the slot-creation window, evaluates booked students using rubrics, submits marks and remarks.
- **Student** — registers, browses examinations, books/cancels slots (respecting booking windows and capacity), views published results with feedback, edits profile.

## Quick start

From this `source/` directory:

**Windows — Command Prompt (cmd.exe):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
python app.py
```

**Windows — PowerShell:**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```
If PowerShell refuses with an execution-policy error, run this once (accept with `Y`), then retry:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**Windows — Git Bash / macOS / Linux:**
```bash
python -m venv .venv
source .venv/Scripts/activate    # Windows Git Bash
# source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
python app.py
```

**Or skip the venv entirely** (installs Flask into your global Python):
```cmd
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000/ in your browser.

### Default Admin credentials

The Admin user is seeded automatically on first run:

- Username: `admin`
- Password: `admin123`

Change these in `config.py` (fields `ADMIN_USERNAME` / `ADMIN_PASSWORD`) or via `EMP_SECRET_KEY` env var for the session secret.

## Database

The SQLite file is created at `source/emp.db` on first run. All tables are defined in `models.py` and created via `CREATE TABLE IF NOT EXISTS` — no manual creation.

To reset the database, stop the server and delete `emp.db`; it will be re-created (and the Admin re-seeded) on next start.

## Folder structure

```
source/
├── app.py                 # Flask application factory + entry point
├── config.py              # Config (secret, DB path, seed Admin credentials)
├── models.py              # SQLite schema + connection helpers + Admin seeding
├── auth.py                # Login / logout / registration blueprint
├── admin.py               # Admin blueprint
├── examiner.py            # Examiner blueprint
├── student.py             # Student blueprint
├── requirements.txt
├── static/
│   └── style.css          # Small Bootstrap overrides
└── templates/
    ├── base.html          # Shared layout (Bootstrap navbar, flash messages)
    ├── index.html         # Landing page
    ├── auth/              # login.html, register.html
    ├── admin/             # dashboard, courses, examinations, rubrics, examiners, students, slots, bookings, reschedule, change_examiner + forms
    ├── examiner/          # dashboard, slots, slot_form, booked_students, evaluate
    ├── student/           # dashboard, examinations, slots, bookings, results, profile
    └── errors/            # 404, 500
```

## Data model (ER outline)

- **users** — id, username, email, password_hash, role (admin/examiner/student), name, contact, department, status (pending/approved/deactivated/active), created_at
- **courses** — id, code, name, description, status
- **examinations** — id, course_id → courses, name, exam_type, duration_minutes, max_marks, slot_create_start/end, slot_book_start/end, status (Draft / Slot Creation / Booking Open / Closed / Completed), results_published
- **rubrics** — id, examination_id → examinations, criterion, max_marks, weightage, description
- **slots** — id, examination_id → examinations, examiner_id → users, slot_date, start_time, end_time, max_capacity, status (Available / Full / Cancelled / Completed)
- **bookings** — id, student_id → users, slot_id → slots, booking_date, status (Booked / Cancelled / Completed); UNIQUE (student_id, slot_id)
- **evaluations** — id, booking_id → bookings, rubric_id → rubrics, marks, remarks; UNIQUE (booking_id, rubric_id)
- **evaluation_summary** — booking_id (PK) → bookings, total_marks, overall_remarks, evaluated_at

## Key business rules enforced

- Admin is the only pre-existing user; no Admin registration.
- Examiner registration → status `pending` → cannot log in until Admin approves.
- Examiners can only create slots when the examination's status is `Slot Creation` AND (if configured) the current time is within `slot_create_start` / `slot_create_end`.
- Slots that have any active booking cannot be edited or deleted by the examiner.
- Students can only book when the examination status is `Booking Open` and (if configured) inside `slot_book_start` / `slot_book_end`.
- Students cannot double-book the same examination (active `Booked` row is enforced at query time; DB has a UNIQUE(student_id, slot_id)).
- Slots automatically transition to `Full` when capacity is reached; cancel-back-to-available on cancellation.
- Examiners can only evaluate students who booked into their own slots.
- Results are hidden from students until Admin explicitly publishes them.
- Booking cancellation is blocked after `slot_book_end`.
- Search available on Admin's Courses / Examinations / Examiners / Students / Bookings pages, and on Student's Examinations page (with type filter).

## No JavaScript for core features

The app is deliberately server-rendered. The only client-side JS is:

- Bootstrap CSS-only components (no Bootstrap JS bundle is loaded).
- Inline `onsubmit="return confirm(...)"` on destructive buttons (delete / cancel / publish). This is a convenience prompt — the server enforces all rules; disabling JS still leaves the app fully functional.
