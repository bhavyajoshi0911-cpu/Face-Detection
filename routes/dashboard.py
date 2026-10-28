import csv
from datetime import date, timedelta
from io import StringIO
from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for
from services.attendance_service import (
	attendance_report_rows,
	attendance_trend,
	department_attendance,
	generate_attendance_report,
	recent_attendance,
	report_departments,
	report_employees,
	today_stats,
)
from services.auth_service import login_required
from services.settings_service import get_settings, save_settings
dashboard_bp = Blueprint('dashboard', __name__)
@dashboard_bp.get('/')
@login_required
def home():
	trend_7 = attendance_trend(7)
	trend_30 = attendance_trend(30)
	department_rows = department_attendance()
	departments = []
	for row in department_rows:
		total = row['total']
		present = row['present'] or 0
		departments.append({
			'department': row['department'],
			'total': total,
			'present': present,
			'absent': max(total - present, 0),
			'percentage': round(present * 100 / total, 1) if total else 0,
		})
	return render_template(
		'dashboard.html',
		stats=today_stats(),
		trend_7=trend_7,
		trend_30=trend_30,
		departments=departments,
		recent=recent_attendance(),
		active='dashboard',
	)
@dashboard_bp.get('/recognition')
@login_required
def recognition(): return render_template('recognition.html', settings=get_settings(), active='recognition')
@dashboard_bp.get('/attendance')
@login_required
def attendance(): return render_template('attendance.html', records=recent_attendance(50), active='attendance')

@dashboard_bp.get('/attendance/export')
@login_required
def export_attendance():
	output = StringIO()
	output.write('\ufeff')
	writer = csv.writer(output)
	writer.writerow(['Employee ID', 'Employee Name', 'Department', 'Date', 'Check In', 'Check Out', 'Status', 'Confidence'])
	for row in attendance_report_rows():
		writer.writerow([
			row['code'], row['name'], row['department'] or '', row['date'],
			row['check_in'][11:19] if row['check_in'] else '',
			row['check_out'][11:19] if row['check_out'] else '',
			row['status'], row['confidence'] if row['confidence'] is not None else '',
		])
	return Response(output.getvalue(), mimetype='text/csv', headers={
		'Content-Disposition': 'attachment; filename="attendance-report.csv"',
	})

@dashboard_bp.get('/reports')
@login_required
def reports():
	today = date.today()
	filters = {
		'date_from': request.args.get('date_from') or (today - timedelta(days=29)).isoformat(),
		'date_to': request.args.get('date_to') or today.isoformat(),
		'employee': request.args.get('employee', '').strip(),
		'department': request.args.get('department', '').strip(),
		'status': request.args.get('status', '').strip(),
	}
	error = None
	try:
		records, summary = generate_attendance_report(
			filters['date_from'], filters['date_to'], filters['employee'],
			filters['department'], filters['status'],
		)
	except ValueError as validation_error:
		records = []
		summary = {
			'total_records': 0, 'present': 0, 'absent': 0,
			'average_working_hours': 0, 'attendance_percentage': 0,
		}
		error = str(validation_error)
	return render_template(
		'reports.html', records=records, summary=summary, filters=filters,
		employees=report_employees(), departments=report_departments(),
		report_error=error, active='reports',
	), 400 if error else 200


@dashboard_bp.get('/reports/export')
@login_required
def export_report():
	today = date.today()
	filters = {
		'date_from': request.args.get('date_from') or (today - timedelta(days=29)).isoformat(),
		'date_to': request.args.get('date_to') or today.isoformat(),
		'employee': request.args.get('employee', '').strip(),
		'department': request.args.get('department', '').strip(),
		'status': request.args.get('status', '').strip(),
	}
	try:
		records, _summary = generate_attendance_report(
			filters['date_from'], filters['date_to'], filters['employee'],
			filters['department'], filters['status'],
		)
	except ValueError as error:
		return Response(str(error), status=400, mimetype='text/plain')
	output = StringIO()
	output.write('\ufeff')
	writer = csv.writer(output)
	writer.writerow(['Employee ID', 'Employee Name', 'Department', 'Date', 'Check In', 'Check Out', 'Working Hours', 'Status'])
	for row in records:
		writer.writerow([
			row['code'], row['name'], row['department'], row['date'],
			row['check_in'][11:19] if row['check_in'] else '',
			row['check_out'][11:19] if row['check_out'] else '',
			row['working_hours'] if row['working_hours'] is not None else '',
			row['status'],
		])
	return Response(output.getvalue(), mimetype='text/csv', headers={
		'Content-Disposition': 'attachment; filename="attendance-report.csv"',
	})
@dashboard_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
	if g.user['role'] != 'Admin':
		abort(403)
	settings_data = get_settings()
	if request.method == 'POST':
		try:
			settings_data = save_settings(request.form)
		except ValueError as error:
			flash(str(error), 'error')
			settings_data = {**settings_data, **request.form}
		else:
			flash('Settings saved.', 'success')
			return redirect(url_for('dashboard.settings'))
	return render_template('settings.html', settings=settings_data, active='settings')
