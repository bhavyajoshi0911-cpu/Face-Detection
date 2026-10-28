from datetime import date
from flask import Blueprint, current_app, jsonify, request, session
from database.database import get_db
from services.attendance_service import recognition_cooldown_remaining, record_attendance, today_stats
from services.auth_service import login_required, authenticate
from services.employee_service import create_employee, list_employees
from services.face_service import available, encode_image, encoding_distance, recognize_image
from services.settings_service import get_settings
api_bp = Blueprint('api', __name__, url_prefix='/api')
def row_dict(row): return dict(row) if row else None
@api_bp.post('/login')
def api_login():
    data=request.get_json(silent=True) or {}; user=authenticate(data.get('username',''), data.get('password',''))
    if not user: return jsonify(success=False, message='Invalid credentials'), 401
    session['user_id']=user['id']; return jsonify(success=True, user={'username':user['username'],'role':user['role']})
@api_bp.get('/dashboard/stats')
@login_required
def stats(): return jsonify(success=True, stats=today_stats())
@api_bp.get('/employees')
@login_required
def employees(): return jsonify(success=True, employees=[row_dict(row) for row in list_employees(request.args.get('search',''), request.args.get('department',''), request.args.get('status',''))])
@api_bp.post('/employees')
@login_required
def add_employee(): return jsonify(success=True, employee=row_dict(create_employee(request.get_json(silent=True) or {}))), 201
@api_bp.get('/attendance')
@login_required
def attendance():
    rows=get_db().execute('SELECT a.*, e.name, e.employee_id AS code FROM attendance a JOIN employees e ON e.id=a.employee_id ORDER BY a.date DESC, a.check_in DESC').fetchall()
    return jsonify(success=True, attendance=[row_dict(row) for row in rows])
@api_bp.post('/attendance/check-in')
@login_required
def check_in():
    return _record_attendance(request.get_json(silent=True) or {}, 'check_in')

@api_bp.post('/attendance/check-out')
@login_required
def check_out():
    return _record_attendance(request.get_json(silent=True) or {}, 'check_out')

def _record_attendance(data, mode):
    employee_id = data.get('employee_id')
    if not employee_id:
        return jsonify(success=False, message='employee_id is required'), 400
    try:
        confidence = float(data.get('confidence', 0))
        if not 0 <= confidence <= 1:
            raise ValueError
        action = record_attendance(employee_id, confidence, mode)
    except (TypeError, ValueError) as error:
        message = str(error) if str(error) == 'Employee not found' else 'Confidence must be between 0 and 1.'
        status = 404 if message == 'Employee not found' else 400
        return jsonify(success=False, message=message), status
    messages = {
        'check_in': 'Check-in recorded successfully.',
        'check_out': 'Check-out recorded successfully.',
        'already_checked_in': 'Already checked in today.',
        'check_in_required': 'Check-in required before check-out.',
        'already_complete': 'Attendance already completed for today.',
    }
    employee = get_db().execute('SELECT id, employee_id, name FROM employees WHERE id = ? OR employee_id = ?', (employee_id, employee_id)).fetchone()
    attendance = get_db().execute(
        'SELECT date, check_in, check_out, status FROM attendance WHERE employee_id = ? AND date = ?',
        (employee['id'], date.today().isoformat()),
    ).fetchone()
    successful = action in {'check_in', 'check_out'}
    return jsonify(
        success=successful,
        message=messages[action],
        action=action,
        employee={'id': employee['employee_id'], 'name': employee['name']},
        attendance=dict(attendance) if attendance else None,
    ), 200 if successful else 409
@api_bp.get('/recognition/logs')
@login_required
def logs():
    rows=get_db().execute('SELECT l.*, e.name, e.employee_id AS code FROM recognition_logs l LEFT JOIN employees e ON e.id=l.employee_id ORDER BY l.recognized_at DESC LIMIT 100').fetchall()
    return jsonify(success=True, logs=[row_dict(row) for row in rows])

@api_bp.get('/face/status')
@login_required
def face_status():
    return jsonify(success=True, available=available())

@api_bp.post('/face/register')
@login_required
def register_face():
    employee_id = (request.form.get('employee_id') or '').strip()
    upload = request.files.get('image')
    if not employee_id or upload is None:
        return jsonify(success=False, message='employee_id and image are required'), 400
    if not available():
        return jsonify(success=False, message='OpenCV face recognition is unavailable on this environment'), 503
    employee = get_db().execute('SELECT id FROM employees WHERE id=? OR employee_id=?', (employee_id, employee_id)).fetchone()
    if employee is None:
        return jsonify(success=False, message='Employee not found'), 404
    try:
        blob = encode_image(upload.read())
    except RuntimeError as error:
        return jsonify(success=False, message=str(error)), 503
    except ValueError as error:
        return jsonify(success=False, message=str(error)), 422
    db = get_db()
    db.execute('INSERT OR REPLACE INTO face_encodings (employee_id, encoding) VALUES (?, ?)', (employee['id'], blob))
    db.commit()
    return jsonify(success=True, message='Face registration completed')

@api_bp.post('/face/recognize')
@login_required
def recognize_face():
    upload = request.files.get('image')
    if upload is None:
        return jsonify(success=False, message='A camera image is required'), 400
    mode = request.form.get('mode', 'check_in')
    if mode not in {'check_in', 'check_out'}:
        return jsonify(success=False, message='Choose check-in or check-out mode.'), 400
    if not available():
        return jsonify(success=False, message='Install face-recognition before using biometric attendance'), 503
    settings = get_settings()
    try:
        encoding, _locations = recognize_image(upload.read(), settings['face_match_threshold'])
    except ValueError as error:
        return jsonify(success=False, message=str(error)), 422
    except RuntimeError as error:
        return jsonify(success=False, message=str(error)), 503
    db = get_db()
    stored = db.execute('SELECT e.*, f.encoding FROM employees e JOIN face_encodings f ON f.employee_id=e.id WHERE e.status="Active"').fetchall()
    if not stored:
        return jsonify(success=False, message='No employee face samples are registered'), 404
    try:
        distances = [(encoding_distance(row['encoding'], encoding), row) for row in stored]
    except ValueError as error:
        return jsonify(success=False, message=str(error)), 422
    distance, employee = min(distances, key=lambda item: item[0])
    confidence = max(0.0, min(1.0, 1.0 - float(distance)))
    if distance > settings['face_match_threshold']:
        db.execute("INSERT INTO recognition_logs (confidence, result) VALUES (?, 'Unknown')", (confidence,))
        db.commit()
        return jsonify(success=False, message='Unknown face', confidence=confidence), 404
    today_attendance = db.execute(
        'SELECT date, check_in, check_out, status FROM attendance WHERE employee_id = ? AND date = ?',
        (employee['id'], date.today().isoformat()),
    ).fetchone()
    if today_attendance and today_attendance['check_in'] and today_attendance['check_out']:
        return jsonify(
            success=False,
            action='already_complete',
            message='Attendance already completed for today.',
            employee={'id': employee['employee_id'], 'name': employee['name']},
            attendance=dict(today_attendance),
        ), 409
    cooldown = settings['recognition_cooldown_seconds']
    remaining = recognition_cooldown_remaining(employee['id'], cooldown)
    if remaining:
        return jsonify(
            success=False, action='cooldown', message=f'Wait {remaining} seconds before scanning this employee again.',
            cooldown_remaining=remaining, employee={'id': employee['employee_id'], 'name': employee['name']},
        ), 429
    action = record_attendance(employee['id'], confidence, mode)
    attendance = db.execute(
        'SELECT date, check_in, check_out, status FROM attendance WHERE employee_id = ? AND date = ?',
        (employee['id'], date.today().isoformat()),
    ).fetchone()
    messages = {
        'check_in': 'Check-in recorded successfully.',
        'check_out': 'Check-out recorded successfully.',
        'already_checked_in': 'Already checked in today.',
        'check_in_required': 'Check-in required before check-out.',
        'already_complete': 'Attendance already completed for today.',
    }
    successful = action in {'check_in', 'check_out'}
    return jsonify(
        success=successful, message=messages[action], action=action, mode=mode,
        confidence=confidence,
        employee={'id': employee['employee_id'], 'name': employee['name']},
        attendance=dict(attendance),
    ), 200 if successful else 409
