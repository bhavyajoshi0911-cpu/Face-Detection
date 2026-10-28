# Nivora AI Attendance

A modular Flask foundation for employee management, attendance, and privacy-aware face recognition.

## Run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python database/init_db.py
python app.py
```

Open http://127.0.0.1:5000. Demo login: `admin` / `admin123`.

## Architecture

- `routes/` owns page and JSON endpoints.
- `services/` owns authentication, employees, attendance, and face encoding boundaries.
- `database/` owns SQLite connection and schema.
- `templates/` and `static/` provide the responsive UI shell.

Face recognition uses OpenCV's YuNet and SFace models. On the first face registration or recognition, the app downloads the official model files from OpenCV Zoo into the ignored `instance/models/` directory; internet access is required once. The camera and face-encoding path do not require the platform-sensitive `dlib` package.

## Security

Passwords are hashed with Werkzeug. Biometric encodings are stored as controlled binary records and cascade-delete with employees. Keep `.env` private, replace the development secret, add CSRF protection before internet deployment, and never store continuous webcam video.
