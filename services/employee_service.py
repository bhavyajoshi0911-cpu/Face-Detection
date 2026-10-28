from database.database import get_db


def list_employees(search="", department="", status=""):
    clauses, values = [], []
    if search:
        clauses.append("(e.name LIKE ? OR e.employee_id LIKE ? OR e.email LIKE ?)")
        values.extend([f"%{search}%"] * 3)
    if department:
        clauses.append("e.department = ?")
        values.append(department)
    if status:
        clauses.append("e.status = ?")
        values.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return get_db().execute(f"""
        SELECT e.*, a.check_in AS last_check_in, a.date AS last_attendance
        FROM employees e LEFT JOIN attendance a ON a.employee_id = e.id
        AND a.date = (SELECT MAX(date) FROM attendance WHERE employee_id = e.id)
        {where} ORDER BY e.created_at DESC
    """, values).fetchall()


def create_employee(data):
    db = get_db()
    cursor = db.execute("""INSERT INTO employees
        (employee_id, name, email, phone, department, designation, joining_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)""", tuple(data.get(key, "") for key in
        ("employee_id", "name", "email", "phone", "department", "designation", "joining_date")))
    db.commit()
    return db.execute("SELECT * FROM employees WHERE id = ?", (cursor.lastrowid,)).fetchone()


def update_employee(employee_id, data):
    db = get_db()
    db.execute("""UPDATE employees SET
        employee_id = ?, name = ?, email = ?, phone = ?, department = ?,
        designation = ?, joining_date = ?, status = ?
        WHERE id = ?""", tuple(data.get(key, "") for key in
        ("employee_id", "name", "email", "phone", "department", "designation", "joining_date", "status")) + (employee_id,))
    db.commit()
    return db.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()


def get_employee(employee_id):
    return get_db().execute("SELECT * FROM employees WHERE id = ? OR employee_id = ?", (employee_id, employee_id)).fetchone()


def delete_employee(employee_id):
    db = get_db()
    db.execute("DELETE FROM employees WHERE id = ? OR employee_id = ?", (employee_id, employee_id))
    db.commit()
