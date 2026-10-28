import math
from flask import current_app
from database.database import get_db


def _defaults():
    return {
        "face_match_threshold": float(current_app.config["FACE_MATCH_THRESHOLD"]),
        "camera_scan_interval_ms": int(current_app.config["CAMERA_SCAN_INTERVAL_MS"]),
        "recognition_cooldown_seconds": int(current_app.config["RECOGNITION_COOLDOWN_SECONDS"]),
        "application_name": current_app.config["APP_NAME"],
    }


def initialize_settings():
    db = get_db()
    defaults = _defaults()
    db.executemany(
        "INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES (?, ?)",
        [(key, str(value)) for key, value in defaults.items()],
    )
    db.commit()


def get_settings():
    settings = _defaults()
    rows = get_db().execute("SELECT setting_key, setting_value FROM app_settings").fetchall()
    for row in rows:
        if row["setting_key"] not in settings:
            continue
        try:
            if row["setting_key"] == "face_match_threshold":
                settings[row["setting_key"]] = float(row["setting_value"])
            elif row["setting_key"] in {"camera_scan_interval_ms", "recognition_cooldown_seconds"}:
                settings[row["setting_key"]] = int(row["setting_value"])
            else:
                settings[row["setting_key"]] = row["setting_value"]
        except (TypeError, ValueError):
            continue
    return settings


def save_settings(form):
    try:
        threshold = float(form.get("face_match_threshold", ""))
    except (TypeError, ValueError) as error:
        raise ValueError("Face threshold must be a number.") from error
    if not math.isfinite(threshold) or not 0.30 <= threshold <= 0.75:
        raise ValueError("Face threshold must be between 0.30 and 0.75.")

    try:
        interval = int(form.get("camera_scan_interval_ms", ""))
    except (TypeError, ValueError) as error:
        raise ValueError("Camera scan interval must be a whole number of milliseconds.") from error
    if not 250 <= interval <= 10000:
        raise ValueError("Camera scan interval must be between 250 and 10000 ms.")

    try:
        cooldown = int(form.get("recognition_cooldown_seconds", ""))
    except (TypeError, ValueError) as error:
        raise ValueError("Recognition cooldown must be a whole number of seconds.") from error
    if not 5 <= cooldown <= 300:
        raise ValueError("Recognition cooldown must be between 5 and 300 seconds.")

    application_name = (form.get("application_name") or "").strip()
    if not application_name or len(application_name) > 80:
        raise ValueError("Application name must contain 1 to 80 characters.")

    values = {
        "face_match_threshold": threshold,
        "camera_scan_interval_ms": interval,
        "recognition_cooldown_seconds": cooldown,
        "application_name": application_name,
    }
    db = get_db()
    db.executemany("""INSERT INTO app_settings (setting_key, setting_value)
        VALUES (?, ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value = excluded.setting_value,
            updated_at = CURRENT_TIMESTAMP""",
        [(key, str(value)) for key, value in values.items()])
    db.commit()
    return get_settings()