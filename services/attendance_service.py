from datetime import date, datetime, timedelta
import math
from database.database import get_db


def today_stats():
    today = date.today().isoformat()
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM employees WHERE status = 'Active'").fetchone()[0]
    row = db.execute("""SELECT
        COUNT(DISTINCT CASE WHEN a.check_in IS NOT NULL THEN a.employee_id END) AS present,
        COUNT(CASE WHEN a.check_in IS NOT NULL THEN 1 END) AS check_ins,
        COUNT(CASE WHEN a.check_out IS NOT NULL THEN 1 END) AS check_outs,
        COUNT(CASE WHEN lower(a.status) = 'late' THEN 1 END) AS late
        FROM attendance a JOIN employees e ON e.id = a.employee_id
        WHERE a.date = ? AND e.status = 'Active'""", (today,)).fetchone()
    present = row["present"] or 0
    return {
        "total": total,
        "present": present,
        "absent": max(total - present, 0),
        "attendance_percentage": round(present * 100 / total, 1) if total else 0,
        "check_ins": row["check_ins"] or 0,
        "check_outs": row["check_outs"] or 0,
        "late": row["late"] or 0,
    }


def attendance_trend(days=7, today=None):
    if not isinstance(days, int) or not 1 <= days <= 366:
        raise ValueError("Trend range must be between 1 and 366 days")
    end_date = today or date.today()
    start_date = end_date - timedelta(days=days - 1)
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM employees WHERE status = 'Active'").fetchone()[0]
    rows = db.execute("""SELECT a.date, COUNT(DISTINCT a.employee_id) AS present
        FROM attendance a JOIN employees e ON e.id = a.employee_id
        WHERE a.date BETWEEN ? AND ? AND a.check_in IS NOT NULL AND e.status = 'Active'
        GROUP BY a.date""", (start_date.isoformat(), end_date.isoformat())).fetchall()
    present_by_date = {row["date"]: row["present"] for row in rows}
    trend = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        present = present_by_date.get(day.isoformat(), 0)
        trend.append({
            "date": day.isoformat(),
            "label": day.strftime("%a, %b %d"),
            "present": present,
            "absent": max(total - present, 0),
            "percentage": round(present * 100 / total, 1) if total else 0,
        })
    return trend


def department_attendance(today=None):
    current_date = (today or date.today()).isoformat()
    return get_db().execute("""SELECT
        COALESCE(NULLIF(TRIM(e.department), ''), 'Unassigned') AS department,
        COUNT(e.id) AS total,
        SUM(CASE WHEN a.check_in IS NOT NULL THEN 1 ELSE 0 END) AS present
        FROM employees e
        LEFT JOIN attendance a ON a.employee_id = e.id AND a.date = ?
        WHERE e.status = 'Active'
        GROUP BY COALESCE(NULLIF(TRIM(e.department), ''), 'Unassigned')
        ORDER BY department""", (current_date,)).fetchall()


def record_attendance(employee_id, confidence=0.0, mode="check_in"):
    if mode not in {"check_in", "check_out"}:
        raise ValueError("Attendance mode must be check_in or check_out")
    db = get_db()
    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("BEGIN IMMEDIATE")
    try:
        employee = db.execute(
            "SELECT id FROM employees WHERE id = ? OR employee_id = ?",
            (employee_id, employee_id),
        ).fetchone()
        if employee is None:
            raise ValueError("Employee not found")
        employee_id = employee["id"]
        record = db.execute(
            "SELECT * FROM attendance WHERE employee_id = ? AND date = ?",
            (employee_id, today),
        ).fetchone()

        if mode == "check_in":
            if record is None:
                db.execute("""INSERT INTO attendance
                    (employee_id, date, check_in, status, confidence)
                    VALUES (?, ?, ?, 'Present', ?)""", (employee_id, today, now, confidence))
                action = "check_in"
            elif record["check_in"] is None:
                db.execute("""UPDATE attendance SET check_in = ?, status = 'Present', confidence = ?
                    WHERE id = ?""", (now, confidence, record["id"]))
                action = "check_in"
            else:
                action = "already_checked_in"
        elif record is None or record["check_in"] is None:
            action = "check_in_required"
        elif record["check_out"] is not None:
            action = "already_complete"
        else:
            db.execute("UPDATE attendance SET check_out = ?, confidence = ? WHERE id = ?", (now, confidence, record["id"]))
            action = "check_out"

        db.execute("INSERT INTO recognition_logs (employee_id, confidence, result) VALUES (?, ?, 'Recognized')", (employee_id, confidence))
        db.commit()
        return action
    except Exception:
        db.rollback()
        raise


def recognition_cooldown_remaining(employee_id, cooldown_seconds):
    if cooldown_seconds <= 0:
        return 0
    row = get_db().execute("""SELECT MIN((julianday('now') - julianday(recognized_at)) * 86400.0) AS elapsed
        FROM recognition_logs WHERE employee_id = ? AND result = 'Recognized'""", (employee_id,)).fetchone()
    if row["elapsed"] is None:
        return 0
    return max(0, math.ceil(cooldown_seconds - max(float(row["elapsed"]), 0)))


def recent_attendance(limit=8):
    return get_db().execute("""SELECT a.*, e.name, e.employee_id AS code, e.department
        FROM attendance a JOIN employees e ON e.id = a.employee_id
        ORDER BY a.date DESC, a.check_in DESC LIMIT ?""", (limit,)).fetchall()


def attendance_report_rows():
    return get_db().execute("""SELECT a.date, a.check_in, a.check_out, a.status, a.confidence,
        e.employee_id AS code, e.name, e.department
        FROM attendance a JOIN employees e ON e.id = a.employee_id
        ORDER BY a.date DESC, a.check_in DESC""").fetchall()


def report_employees():
    return get_db().execute("""SELECT employee_id, name FROM employees
        ORDER BY name, employee_id""").fetchall()


def report_departments():
    return get_db().execute("""SELECT DISTINCT
        COALESCE(NULLIF(TRIM(department), ''), 'Unassigned') AS department
        FROM employees WHERE status = 'Active' ORDER BY department""").fetchall()


def generate_attendance_report(date_from, date_to, employee_code="", department="", status=""):
    try:
        start_date = date.fromisoformat(date_from)
        end_date = date.fromisoformat(date_to)
    except (TypeError, ValueError) as error:
        raise ValueError("Enter valid start and end dates.") from error
    if start_date > end_date:
        raise ValueError("Start date must not be after end date.")
    if (end_date - start_date).days > 365:
        raise ValueError("Report date range cannot exceed 366 days.")
    if status and status not in {"Present", "Absent", "Late"}:
        raise ValueError("Choose a valid attendance status.")

    start_text = start_date.isoformat()
    end_text = end_date.isoformat()
    rows = get_db().execute("""WITH RECURSIVE report_days(day) AS (
            SELECT date(?)
            UNION ALL
            SELECT date(day, '+1 day') FROM report_days WHERE day < date(?)
        ), report_rows AS (
            SELECT e.employee_id AS code, e.name,
                COALESCE(NULLIF(TRIM(e.department), ''), 'Unassigned') AS department,
                report_days.day AS date, a.check_in, a.check_out,
                CASE
                    WHEN a.check_in IS NULL THEN 'Absent'
                    WHEN lower(COALESCE(a.status, 'present')) = 'late' THEN 'Late'
                    ELSE 'Present'
                END AS status,
                CASE
                    WHEN a.check_in IS NOT NULL AND a.check_out IS NOT NULL
                        AND julianday(a.check_out) >= julianday(a.check_in)
                    THEN ROUND((julianday(a.check_out) - julianday(a.check_in)) * 24.0, 2)
                    ELSE NULL
                END AS working_hours
            FROM employees e CROSS JOIN report_days
            LEFT JOIN attendance a ON a.employee_id = e.id AND a.date = report_days.day
            WHERE (e.status = 'Active' OR EXISTS (
                SELECT 1 FROM attendance history
                WHERE history.employee_id = e.id AND history.date BETWEEN ? AND ?
            ))
        )
        SELECT * FROM report_rows
        WHERE (? = '' OR code = ?)
            AND (? = '' OR department = ?)
            AND (? = '' OR status = ?)
        ORDER BY date DESC, name, code""",
        (start_text, end_text, start_text, end_text,
         employee_code, employee_code, department, department, status, status)).fetchall()

    present = sum(row["status"] in {"Present", "Late"} for row in rows)
    absent = sum(row["status"] == "Absent" for row in rows)
    working_hours = [row["working_hours"] for row in rows if row["working_hours"] is not None]
    total = len(rows)
    summary = {
        "total_records": total,
        "present": present,
        "absent": absent,
        "average_working_hours": round(sum(working_hours) / len(working_hours), 2) if working_hours else 0,
        "attendance_percentage": round(present * 100 / total, 1) if total else 0,
    }
    return rows, summary
