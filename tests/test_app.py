from io import BytesIO
from datetime import datetime
import json
import re
import pytest
from app import create_app

@pytest.fixture
def client(tmp_path):
    app = create_app({'TESTING': True, 'DATABASE_PATH': str(tmp_path / 'test.db'), 'SECRET_KEY': 'test'})
    return app.test_client()

def login(client):
    return client.post('/login', data={'username':'admin','password':'admin123'}, follow_redirects=True)

def test_login_and_dashboard(client):
    response = login(client)
    assert response.status_code == 200
    assert b'Good morning' in response.data
    current_date = datetime.now()
    expected_date = f"{current_date.strftime('%A, %B')} {current_date.day}, {current_date.year}"
    assert expected_date.encode() in response.data

def test_settings_defaults_are_seeded_without_duplicates(client):
    login(client)
    from database.database import get_db
    from services.settings_service import get_settings, initialize_settings
    with client.application.app_context():
        original_count = get_db().execute('SELECT COUNT(*) FROM app_settings').fetchone()[0]
        initialize_settings()
        settings = get_settings()
        new_count = get_db().execute('SELECT COUNT(*) FROM app_settings').fetchone()[0]

    assert settings['face_match_threshold'] == 0.5
    assert settings['camera_scan_interval_ms'] == 1000
    assert settings['recognition_cooldown_seconds'] == 30
    assert settings['application_name'] == 'Nivora'
    assert new_count == original_count == 4

def test_admin_settings_persist_and_reject_invalid_values(client):
    login(client)
    page = client.get('/settings')
    assert page.status_code == 200
    assert b'name="camera_scan_interval_ms"' in page.data
    response = client.post('/settings', data={
        'face_match_threshold':'0.62',
        'camera_scan_interval_ms':'1500',
        'recognition_cooldown_seconds':'45',
        'application_name':'Nivora Operations',
    }, follow_redirects=True)
    assert b'Nivora Operations' in response.data

    from database.database import get_db
    from services.settings_service import get_settings
    with client.application.app_context():
        saved = get_settings()
        before_invalid = get_db().execute('SELECT COUNT(*) FROM app_settings').fetchone()[0]
    assert saved['face_match_threshold'] == 0.62
    assert saved['camera_scan_interval_ms'] == 1500
    assert saved['recognition_cooldown_seconds'] == 45
    assert saved['application_name'] == 'Nivora Operations'

    invalid = client.post('/settings', data={
        'face_match_threshold':'0.99',
        'camera_scan_interval_ms':'1500',
        'recognition_cooldown_seconds':'45',
        'application_name':'Nivora Operations',
    }, follow_redirects=True)
    assert b'Face threshold must be between 0.30 and 0.75.' in invalid.data
    with client.application.app_context():
        assert get_settings()['face_match_threshold'] == 0.62
        assert get_db().execute('SELECT COUNT(*) FROM app_settings').fetchone()[0] == before_invalid

    invalid_interval = client.post('/settings', data={
        'face_match_threshold':'0.62',
        'camera_scan_interval_ms':'100',
        'recognition_cooldown_seconds':'45',
        'application_name':'Nivora Operations',
    }, follow_redirects=True)
    assert b'Camera scan interval must be between 250 and 10000 ms.' in invalid_interval.data
    with client.application.app_context():
        assert get_settings()['camera_scan_interval_ms'] == 1500

def test_settings_reject_staff_users(client):
    from werkzeug.security import generate_password_hash
    from database.database import get_db
    with client.application.app_context():
        cursor = get_db().execute(
            'INSERT INTO users (username,email,password_hash,role) VALUES (?,?,?,?)',
            ('staff','staff@example.com',generate_password_hash('staff-pass'),'Staff'),
        )
        get_db().commit()
        staff_id = cursor.lastrowid
    with client.session_transaction() as session:
        session['user_id'] = staff_id

    assert client.get('/settings').status_code == 403
    assert client.post('/settings', data={}).status_code == 403

def test_dashboard_analytics_use_database_and_fill_empty_dates(client):
    login(client)
    from services.attendance_service import attendance_trend, department_attendance, record_attendance, today_stats
    from database.database import get_db
    from datetime import date

    with client.application.app_context():
        empty_trend = attendance_trend(7)
        assert len(empty_trend) == 7
        assert all(point['present'] == point['absent'] == point['percentage'] == 0 for point in empty_trend)
        assert today_stats()['attendance_percentage'] == 0

    first = client.post('/api/employees', json={'employee_id':'EMP-A1','name':'Alex One','department':'Engineering'}).json['employee']
    client.post('/api/employees', json={'employee_id':'EMP-A2','name':'Alex Two','department':'Engineering'}).json['employee']
    with client.application.app_context():
        db = get_db()
        employee = db.execute('SELECT id FROM employees WHERE employee_id = ?', (first['employee_id'],)).fetchone()
        record_attendance(employee['id'])
        stats = today_stats()
        trend = attendance_trend(7)
        departments = department_attendance()

    assert stats['total'] == 2
    assert stats['present'] == 1
    assert stats['absent'] == 1
    assert stats['attendance_percentage'] == 50
    assert stats['check_ins'] == 1
    assert stats['check_outs'] == 0
    assert trend[-1]['date'] == date.today().isoformat()
    assert trend[-1]['present'] == 1
    assert trend[-1]['absent'] == 1
    assert departments[0]['department'] == 'Engineering'
    assert departments[0]['total'] == 2
    assert departments[0]['present'] == 1

def test_dashboard_embeds_zero_filled_chart_data_without_mock_values(client):
    login(client)
    response = client.get('/')
    match = re.search(rb'<script id="dashboardAnalytics" type="application/json">(.*?)</script>', response.data, re.S)

    assert response.status_code == 200
    assert match is not None
    payload = json.loads(match.group(1))
    assert len(payload['trend_7']) == 7
    assert len(payload['trend_30']) == 30
    assert all(point['present'] == point['absent'] == point['percentage'] == 0 for point in payload['trend_7'])
    assert payload['departments'] == []
    assert b'92%' not in response.data

def test_attendance_report_filters_and_calculates_absences(client):
    login(client)
    from datetime import date
    from database.database import get_db
    from services.attendance_service import generate_attendance_report, record_attendance
    first = client.post('/api/employees', json={'employee_id':'EMP-R1','name':'Report One','department':'Support'}).json['employee']
    client.post('/api/employees', json={'employee_id':'EMP-R2','name':'Report Two','department':'Support'})
    with client.application.app_context():
        employee = get_db().execute('SELECT id FROM employees WHERE employee_id = ?', (first['employee_id'],)).fetchone()
        record_attendance(employee['id'])
        records, summary = generate_attendance_report(date.today().isoformat(), date.today().isoformat(), department='Support')
        absent_records, absent_summary = generate_attendance_report(
            date.today().isoformat(), date.today().isoformat(), department='Support', status='Absent')

    assert len(records) == 2
    assert {row['status'] for row in records} == {'Present', 'Absent'}
    assert summary['total_records'] == 2
    assert summary['present'] == 1
    assert summary['absent'] == 1
    assert summary['attendance_percentage'] == 50
    assert len(absent_records) == 1
    assert absent_summary['absent'] == 1

def test_filtered_report_csv_and_invalid_dates(client):
    login(client)
    from datetime import date
    client.post('/api/employees', json={'employee_id':'EMP-CSV-REPORT','name':'CSV Report','department':'Quality'})
    today = date.today().isoformat()
    response = client.get('/reports/export', query_string={
        'date_from':today, 'date_to':today, 'department':'Quality', 'status':'Absent',
    })

    assert response.status_code == 200
    assert response.mimetype == 'text/csv'
    assert b'EMP-CSV-REPORT,CSV Report,Quality' in response.data
    assert b',Absent' in response.data
    assert client.get('/reports', query_string={'date_from':'bad-date'}).status_code == 400

def test_report_calculates_working_hours_and_employee_filter(client):
    login(client)
    from datetime import date
    from database.database import get_db
    employee = client.post('/api/employees', json={
        'employee_id':'EMP-HOURS', 'name':'Hours Person', 'department':'Support',
    }).json['employee']
    today = date.today().isoformat()
    with client.application.app_context():
        db = get_db()
        employee_row = db.execute('SELECT id FROM employees WHERE employee_id = ?', (employee['employee_id'],)).fetchone()
        db.execute("""INSERT INTO attendance (employee_id, date, check_in, check_out, status, confidence)
            VALUES (?, ?, ?, ?, 'Present', 0.9)""", (
            employee_row['id'], today, f'{today} 09:00:00', f'{today} 17:30:00',
        ))
        db.commit()

    report = client.get('/reports', query_string={
        'date_from':today, 'date_to':today, 'employee':employee['employee_id'],
    })
    assert report.status_code == 200
    assert b'8.5 h' in report.data
    assert b'Hours Person' in report.data

def test_employee_creation_and_api(client):
    login(client)
    response = client.post('/api/employees', json={'employee_id':'EMP-001','name':'Ari Chen','department':'Engineering'})
    assert response.status_code == 201
    assert response.json['employee']['name'] == 'Ari Chen'

def test_employee_list_can_delete_employee(client):
    login(client)
    employee = client.post('/api/employees', json={'employee_id':'EMP-DELETE','name':'Delete Person'}).json['employee']
    listing = client.get('/employees')

    assert listing.status_code == 200
    assert b'aria-label="Delete Delete Person"' in listing.data
    assert f'action="/employees/{employee["id"]}/delete"'.encode() in listing.data
    assert b'return confirm(' in listing.data

    response = client.post(f"/employees/{employee['id']}/delete")
    assert response.status_code == 302
    assert client.get(f"/employees/{employee['id']}").status_code == 404

def test_employee_profile_can_be_edited(client):
    login(client)
    employee = client.post('/api/employees', json={'employee_id':'EMP-005','name':'Sam Lee'}).json['employee']
    edit_form = client.get(f"/employees/{employee['id']}/edit")
    assert edit_form.status_code == 200
    assert b'value="Sam Lee"' in edit_form.data
    response = client.post(f"/employees/{employee['id']}/edit", data={
        'employee_id':'EMP-005', 'name':'Sam Lee Updated', 'email':'sam@example.com',
        'phone':'555-0100', 'department':'Operations', 'designation':'Coordinator',
        'joining_date':'2026-09-29', 'status':'Active',
    })

    assert response.status_code == 302
    profile = client.get(f"/employees/{employee['id']}")
    assert b'Sam Lee Updated' in profile.data
    assert b'sam@example.com' in profile.data
    assert b'aria-label="Edit employee details"' in profile.data
    assert f'href="/employees/{employee["id"]}/edit"'.encode() in profile.data

def test_attendance_report_downloads_csv(client):
    login(client)
    employee = client.post('/api/employees', json={
        'employee_id':'EMP-CSV', 'name':'Export Person', 'department':'Engineering',
    }).json['employee']
    client.post('/api/attendance/check-in', json={'employee_id':employee['employee_id'], 'confidence':0.95})

    response = client.get('/attendance/export')

    assert response.status_code == 200
    assert response.mimetype == 'text/csv'
    assert 'attachment; filename="attendance-report.csv"' in response.headers['Content-Disposition']
    assert b'EMP-CSV,Export Person,Engineering' in response.data

def test_api_requires_auth(client):
    response = client.get('/api/dashboard/stats')
    assert response.status_code == 401

def test_face_status_reports_opencv_backend(client):
    login(client)
    response = client.get('/api/face/status')
    assert response.status_code == 200
    assert response.json == {'success': True, 'available': True}

def test_face_recognition_marks_attendance(client, monkeypatch):
    login(client)
    employee = client.post('/api/employees', json={'employee_id':'EMP-003','name':'Noah Kim'}).json['employee']
    from database.database import get_db
    with client.application.app_context():
        db = get_db()
        row = db.execute('SELECT id FROM employees WHERE employee_id = ?', (employee['employee_id'],)).fetchone()
        db.execute('INSERT INTO face_encodings (employee_id, encoding) VALUES (?, ?)', (row['id'], b'sample'))
        db.commit()

    import routes.api as api
    monkeypatch.setattr(api, 'recognize_image', lambda image, threshold: (object(), None))
    monkeypatch.setattr(api, 'encoding_distance', lambda blob, encoding: 0.1)
    response = client.post('/api/face/recognize', data={'image': (BytesIO(b'image'), 'capture.jpg')})

    assert response.status_code == 200
    assert response.json['employee']['name'] == 'Noah Kim'
    assert response.json['action'] == 'check_in'
    assert response.json['attendance']['date']
    assert response.json['attendance']['check_in']
    assert response.json['attendance']['check_out'] is None

def test_face_recognition_uses_saved_threshold(client, monkeypatch):
    login(client)
    from database.database import get_db
    from services.settings_service import save_settings
    with client.application.app_context():
        save_settings({
            'face_match_threshold':'0.62', 'camera_scan_interval_ms':'1000',
            'recognition_cooldown_seconds':'30', 'application_name':'Nivora',
        })
        db = get_db()
        employee = db.execute('SELECT id FROM employees WHERE employee_id = ?', ('001',)).fetchone()
        if employee is None:
            cursor = db.execute("INSERT INTO employees (employee_id, name) VALUES ('001', 'Threshold User')")
            employee_id = cursor.lastrowid
        else:
            employee_id = employee['id']
        db.execute('INSERT INTO face_encodings (employee_id, encoding) VALUES (?, ?)', (employee_id, b'sample'))
        db.commit()

    import routes.api as api
    thresholds = []
    monkeypatch.setattr(api, 'recognize_image', lambda image, threshold: (thresholds.append(threshold) or object(), None))
    monkeypatch.setattr(api, 'encoding_distance', lambda blob, encoding: 0.55)
    response = client.post('/api/face/recognize', data={'image': (BytesIO(b'image'), 'capture.jpg')})

    assert response.status_code == 200
    assert thresholds == [0.62]

def test_unknown_face_does_not_create_attendance(client, monkeypatch):
    login(client)
    employee = client.post('/api/employees', json={'employee_id':'EMP-UNKNOWN','name':'Known Person'}).json['employee']
    from database.database import get_db
    with client.application.app_context():
        employee_row = get_db().execute('SELECT id FROM employees WHERE employee_id = ?', (employee['employee_id'],)).fetchone()
        get_db().execute('INSERT INTO face_encodings (employee_id, encoding) VALUES (?, ?)', (employee_row['id'], b'sample'))
        get_db().commit()

    import routes.api as api
    monkeypatch.setattr(api, 'recognize_image', lambda image, threshold: (object(), None))
    monkeypatch.setattr(api, 'encoding_distance', lambda blob, encoding: 0.9)
    response = client.post('/api/face/recognize', data={'image':(BytesIO(b'image'),'unknown.jpg')})

    assert response.status_code == 404
    assert response.json['message'] == 'Unknown face'
    with client.application.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM attendance').fetchone()[0] == 0
        assert get_db().execute("SELECT result FROM recognition_logs").fetchone()['result'] == 'Unknown'

def test_recognition_selects_best_match_across_multiple_employees(client, monkeypatch):
    login(client)
    first = client.post('/api/employees', json={'employee_id':'EMP-M1','name':'First Match'}).json['employee']
    second = client.post('/api/employees', json={'employee_id':'EMP-M2','name':'Best Match'}).json['employee']
    from database.database import get_db
    with client.application.app_context():
        db = get_db()
        first_row = db.execute('SELECT id FROM employees WHERE employee_id = ?', (first['employee_id'],)).fetchone()
        second_row = db.execute('SELECT id FROM employees WHERE employee_id = ?', (second['employee_id'],)).fetchone()
        db.execute('INSERT INTO face_encodings (employee_id, encoding) VALUES (?, ?)', (first_row['id'], b'first'))
        db.execute('INSERT INTO face_encodings (employee_id, encoding) VALUES (?, ?)', (second_row['id'], b'second'))
        db.commit()

    import routes.api as api
    monkeypatch.setattr(api, 'recognize_image', lambda image, threshold: (object(), None))
    monkeypatch.setattr(api, 'encoding_distance', lambda blob, encoding: 0.1 if blob == b'second' else 0.3)
    response = client.post('/api/face/recognize', data={'image':(BytesIO(b'image'),'capture.jpg')})

    assert response.status_code == 200
    assert response.json['employee']['id'] == second['employee_id']

def test_recognition_cooldown_blocks_duplicates_but_allows_later_checkout(client, monkeypatch):
    login(client)
    employee = client.post('/api/employees', json={'employee_id':'EMP-COOL','name':'Cooldown User'}).json['employee']
    from database.database import get_db
    with client.application.app_context():
        employee_row = get_db().execute('SELECT id FROM employees WHERE employee_id = ?', (employee['employee_id'],)).fetchone()
        get_db().execute('INSERT INTO face_encodings (employee_id, encoding) VALUES (?, ?)', (employee_row['id'], b'sample'))
        get_db().commit()

    import routes.api as api
    monkeypatch.setattr(api, 'recognize_image', lambda image, threshold: (object(), None))
    monkeypatch.setattr(api, 'encoding_distance', lambda blob, encoding: 0.1)
    first = client.post('/api/face/recognize', data={
        'mode':'check_in', 'image':(BytesIO(b'image'), 'capture.jpg'),
    })
    repeated = client.post('/api/face/recognize', data={
        'mode':'check_out', 'image':(BytesIO(b'image'), 'capture.jpg'),
    })

    assert first.status_code == 200
    assert first.json['action'] == 'check_in'
    assert repeated.status_code == 429
    assert repeated.json['action'] == 'cooldown'
    with client.application.app_context():
        db = get_db()
        attendance = db.execute('SELECT check_out FROM attendance WHERE employee_id = ?', (employee_row['id'],)).fetchone()
        assert attendance['check_out'] is None
        db.execute("UPDATE recognition_logs SET recognized_at = datetime('now', '-1 minute') WHERE employee_id = ?", (employee_row['id'],))
        db.commit()

    checkout = client.post('/api/face/recognize', data={
        'mode':'check_out', 'image':(BytesIO(b'image'), 'capture.jpg'),
    })
    assert checkout.status_code == 200
    assert checkout.json['action'] == 'check_out'

def test_completed_employee_is_not_processed_again_that_day(client, monkeypatch):
    login(client)
    employee = client.post('/api/employees', json={'employee_id':'EMP-DONE','name':'Completed User'}).json['employee']
    from datetime import date
    from database.database import get_db
    today = date.today().isoformat()
    with client.application.app_context():
        db = get_db()
        employee_row = db.execute('SELECT id FROM employees WHERE employee_id = ?', (employee['employee_id'],)).fetchone()
        db.execute('INSERT INTO face_encodings (employee_id, encoding) VALUES (?, ?)', (employee_row['id'], b'sample'))
        db.execute("""INSERT INTO attendance (employee_id, date, check_in, check_out, status)
            VALUES (?, ?, ?, ?, 'Present')""", (
            employee_row['id'], today, f'{today} 09:00:00', f'{today} 17:00:00',
        ))
        db.commit()

    import routes.api as api
    monkeypatch.setattr(api, 'recognize_image', lambda image, threshold: (object(), None))
    monkeypatch.setattr(api, 'encoding_distance', lambda blob, encoding: 0.1)
    monkeypatch.setattr(api, 'record_attendance', lambda *args, **kwargs: pytest.fail('Completed attendance must not be processed again'))
    response = client.post('/api/face/recognize', data={
        'mode':'check_out', 'image':(BytesIO(b'image'), 'capture.jpg'),
    })

    assert response.status_code == 409
    assert response.json['action'] == 'already_complete'
    assert response.json['employee']['id'] == employee['employee_id']
    with client.application.app_context():
        db = get_db()
        assert db.execute('SELECT COUNT(*) FROM recognition_logs').fetchone()[0] == 0
        record = db.execute('SELECT check_out FROM attendance WHERE employee_id = ?', (employee_row['id'],)).fetchone()
        assert record['check_out'] == f'{today} 17:00:00'

def test_recognition_page_shows_modes_and_saved_scan_settings(client):
    login(client)
    from services.settings_service import save_settings
    with client.application.app_context():
        save_settings({
            'face_match_threshold':'0.60', 'camera_scan_interval_ms':'1250',
            'recognition_cooldown_seconds':'40', 'application_name':'Nivora',
        })

    response = client.get('/recognition')
    assert response.status_code == 200
    assert b'id="checkInMode"' in response.data
    assert b'id="checkOutMode"' in response.data
    assert b'data-scan-interval="1250"' in response.data
    assert b'1250 ms' in response.data
    assert b'40 seconds' in response.data

def test_employee_face_enrollment_updates_profile_status(client, monkeypatch):
    login(client)
    employee = client.post('/api/employees', json={'employee_id':'EMP-004','name':'Lea Wong'}).json['employee']
    import routes.api as api
    monkeypatch.setattr(api, 'encode_image', lambda image: b'sface-sample')
    response = client.post('/api/face/register', data={
        'employee_id': employee['employee_id'],
        'image': (BytesIO(b'image'), 'face.jpg'),
    })
    profile = client.get('/employees/EMP-004')

    assert response.status_code == 200
    assert b'Face registered' in profile.data

def test_attendance_transitions_from_checkin_to_checkout(client):
    login(client)
    employee = client.post('/api/employees', json={'employee_id':'EMP-002','name':'Mina Park'}).json['employee']
    first = client.post('/api/attendance/check-in', json={'employee_id': employee['employee_id'], 'confidence': 0.92})
    second = client.post('/api/attendance/check-in', json={'employee_id': employee['employee_id'], 'confidence': 0.92})
    checkout = client.post('/api/attendance/check-out', json={'employee_id': employee['employee_id'], 'confidence': 0.92})
    completed = client.post('/api/attendance/check-out', json={'employee_id': employee['employee_id'], 'confidence': 0.92})
    assert first.json['action'] == 'check_in'
    assert second.status_code == 409
    assert second.json['action'] == 'already_checked_in'
    assert checkout.json['action'] == 'check_out'
    assert completed.status_code == 409
    assert completed.json['action'] == 'already_complete'

def test_checkout_requires_a_checkin(client):
    login(client)
    employee = client.post('/api/employees', json={'employee_id':'EMP-OUT','name':'Checkout First'}).json['employee']
    response = client.post('/api/attendance/check-out', json={'employee_id':employee['employee_id']})

    assert response.status_code == 409
    assert response.json['success'] is False
    assert response.json['action'] == 'check_in_required'
    assert response.json['message'] == 'Check-in required before check-out.'
