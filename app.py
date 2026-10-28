import os
from datetime import timedelta
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from config import Config
from database.database import close_db, init_db
from services.auth_service import ensure_default_admin, load_logged_in_user
from services.settings_service import get_settings, initialize_settings

def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    app.permanent_session_lifetime = timedelta(minutes=app.config['SESSION_TIMEOUT_MINUTES'])
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
        ensure_default_admin()
        initialize_settings()
    @app.before_request
    def before_request():
        load_logged_in_user()
    @app.context_processor
    def inject_helpers():
        from datetime import datetime
        return {'now': datetime.now, 'app_name': get_settings()['application_name']}
    @app.errorhandler(Exception)
    def handle_error(error):
        if isinstance(error, HTTPException):
            status, message = error.code, error.description
        else:
            app.logger.exception('Unhandled application error')
            status, message = 500, 'Something went wrong. Please try again.'
        if request.path.startswith('/api/'):
            return jsonify(success=False, message=message), status
        return render_template('error.html', message=message, status=status), status
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.employees import employees_bp
    from routes.api import api_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(api_bp)
    return app

app = create_app()
if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG', '1') == '1')
