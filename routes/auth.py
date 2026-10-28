from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from services.auth_service import authenticate
auth_bp = Blueprint('auth', __name__)
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = authenticate(request.form.get('username', '').strip(), request.form.get('password', ''))
        if user is None:
            flash('Invalid credentials. Try admin / admin123 for the demo account.', 'error')
        else:
            session.clear(); session.permanent = True; session['user_id'] = user['id']
            return redirect(request.args.get('next') or url_for('dashboard.home'))
    return render_template('login.html')
@auth_bp.post('/logout')
def logout():
    session.clear(); return redirect(url_for('auth.login'))
