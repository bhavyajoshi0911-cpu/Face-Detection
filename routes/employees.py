import sqlite3
from flask import Blueprint, flash, redirect, render_template, request, url_for
from database.database import get_db
from services.auth_service import login_required
from services.employee_service import create_employee, delete_employee, get_employee, list_employees, update_employee
employees_bp = Blueprint('employees', __name__, url_prefix='/employees')
@employees_bp.get('')
@login_required
def index(): return render_template('employees.html', employees=list_employees(request.args.get('search',''), request.args.get('department',''), request.args.get('status','')), active='employees')
@employees_bp.route('/new', methods=['GET','POST'])
@login_required
def new():
    if request.method == 'POST':
        try:
            create_employee(request.form); flash('Employee profile created.', 'success'); return redirect(url_for('employees.index'))
        except sqlite3.IntegrityError: flash('That employee ID is already in use.', 'error')
    return render_template('employee_form.html', active='employees')
@employees_bp.get('/<employee_id>')
@login_required
def detail(employee_id):
    employee = get_employee(employee_id)
    if employee is None: return 'Employee not found', 404
    face_registered = get_db().execute('SELECT 1 FROM face_encodings WHERE employee_id = ?', (employee['id'],)).fetchone() is not None
    return render_template('employee_detail.html', employee=employee, face_registered=face_registered, active='employees')

@employees_bp.route('/<employee_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(employee_id):
    employee = get_employee(employee_id)
    if employee is None: return 'Employee not found', 404
    if request.method == 'POST':
        try:
            update_employee(employee['id'], request.form)
            flash('Employee profile updated.', 'success')
            return redirect(url_for('employees.detail', employee_id=employee['id']))
        except sqlite3.IntegrityError:
            flash('That employee ID is already in use.', 'error')
    return render_template('employee_form.html', employee=employee, active='employees')

@employees_bp.post('/<employee_id>/delete')
@login_required
def delete(employee_id):
    delete_employee(employee_id); flash('Employee removed.', 'success'); return redirect(url_for('employees.index'))
