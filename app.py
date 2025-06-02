from dotenv import load_dotenv
import os

load_dotenv()  # Load environment variables from .env

CLIENT_ID = os.getenv('AZURE_CLIENT_ID')
CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET')
TENANT_ID = os.getenv('AZURE_TENANT_ID')
REDIRECT_PATH = os.getenv('AZURE_REDIRECT_PATH', '/auth/redirect')
AUTHORITY = f'https://login.microsoftonline.com/{TENANT_ID}'
SCOPE = ['User.Read']

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort
import msal
import requests
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = 'secret'  # for session management
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
db = SQLAlchemy(app)

# Database Models
class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    email = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(128))  # hashed password
    role = db.Column(db.String(20), default='employee')

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    action_type = db.Column(db.String(20))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Create DB tables
with app.app_context():
    db.create_all()

# Decorators
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'employee_id' not in session:
            return redirect(url_for('index'))
        employee = Employee.query.get(session['employee_id'])
        if not employee or employee.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    if 'employee_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')


# Traditional login (POST)
@app.route('/login', methods=['POST'])
def login():
    session.clear()  # clear any previous session
    email = request.form['email']
    password = request.form['password']
    employee = Employee.query.filter_by(email=email, password=password).first()
    if employee:
        session['employee_id'] = employee.id
        session['employee_name'] = employee.name
        session['employee_role'] = employee.role
        if employee.role == 'admin':
            return redirect(url_for('admin_users'))
        else:
            return redirect(url_for('dashboard'))
    return 'Invalid credentials', 401

# MSAL login (GET)
@app.route('/login')
def msal_login():
    session.clear()
    msal_app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )
    # Build the authorization URL for Microsoft login
    auth_url = msal_app.get_authorization_request_url(
        SCOPE,
        redirect_uri=request.base_url.replace('/login', REDIRECT_PATH)
    )
    return redirect(auth_url)

# MSAL redirect/callback
@app.route(REDIRECT_PATH)
def authorized():
    code = request.args.get('code')
    if not code:
        return 'Authorization failed.', 401

    msal_app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPE,
        redirect_uri=request.base_url
    )

    if 'access_token' in result:
        # Retrieve user profile from Microsoft Graph API
        graph_data = requests.get(
            'https://graph.microsoft.com/v1.0/me',
            headers={'Authorization': f"Bearer {result['access_token']}"}
        ).json()

        email = graph_data.get('mail') or graph_data.get('userPrincipalName')
        name = graph_data.get('displayName', 'No Name')

        # Check if user exists in Employee DB
        employee = Employee.query.filter_by(email=email).first()
        if not employee:
            # Optionally create a new employee if needed
            employee = Employee(
                name=name,
                email=email,
                password='',  # No local password since using SSO
                role='employee'  # Default to employee
            )
            db.session.add(employee)
            db.session.commit()

        session['employee_id'] = employee.id
        session['employee_name'] = employee.name
        session['employee_role'] = employee.role

        # Redirect to dashboard or admin page
        if employee.role == 'admin':
            return redirect(url_for('admin_users'))
        else:
            return redirect(url_for('dashboard'))
    else:
        return 'Failed to acquire access token.', 401

@app.route('/dashboard')
def dashboard():
    if 'employee_id' not in session:
        return redirect(url_for('index'))

    # Role check: only employees can access the dashboard
    if session.get('employee_role') != 'employee':
        return redirect(url_for('admin_users'))

    # Determine current status
    last_record = Attendance.query.filter_by(employee_id=session['employee_id'])\
                                  .order_by(Attendance.timestamp.desc())\
                                  .first()

    if last_record:
        if last_record.action_type == 'login' or last_record.action_type == 'break_end':
            status = 'Working'
        elif last_record.action_type == 'break_start':
            status = 'On Break'
        elif last_record.action_type == 'logout':
            status = 'Not Working'
        else:
            status = 'Unknown'
    else:
        status = 'Not Working'

    return render_template('dashboard.html', name=session['employee_name'], status=status)

@app.route('/attendance', methods=['POST'])
def mark_attendance():
    if 'employee_id' not in session:
        return jsonify({"message": "Unauthorized"}), 401
    data = request.json
    new_entry = Attendance(
        employee_id=session['employee_id'],
        action_type=data['action_type'],
        timestamp=datetime.utcnow()
    )
    db.session.add(new_entry)
    db.session.commit()
    return jsonify({"message": f"{data['action_type']} marked!"})

@app.route('/logout')
def logout():
    session.clear()
    # Redirect to Microsoft logout endpoint
    ms_logout_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/logout'
    post_logout_redirect_uri = url_for('index', _external=True)
    logout_url = f"{ms_logout_url}?post_logout_redirect_uri={post_logout_redirect_uri}"
    return redirect(logout_url)

@app.route('/attendance')
def view_attendance():
    if 'employee_id' not in session:
        return redirect(url_for('index'))

    records = Attendance.query.filter_by(employee_id=session['employee_id']).order_by(Attendance.timestamp.asc()).all()

    work_start = None
    break_start = None
    total_work = 0
    total_break = 0

    for r in records:
        if r.action_type == 'login':
            work_start = r.timestamp
        elif r.action_type == 'logout' and work_start:
            total_work += (r.timestamp - work_start).total_seconds()
            work_start = None
        elif r.action_type == 'break_start' and work_start:
            break_start = r.timestamp
        elif r.action_type == 'break_end' and break_start:
            total_break += (r.timestamp - break_start).total_seconds()
            break_start = None

    net_work = max(total_work - total_break, 0)

    work_hours = int(total_work // 3600)
    work_minutes = int((total_work % 3600) // 60)
    break_hours = int(total_break // 3600)
    break_minutes = int((total_break % 3600) // 60)
    net_work_hours = int(net_work // 3600)
    net_work_minutes = int((net_work % 3600) // 60)

    return render_template(
        'logs.html',
        records=records,
        work_hours=work_hours,
        work_minutes=work_minutes,
        break_hours=break_hours,
        break_minutes=break_minutes,
        net_work_hours=net_work_hours,
        net_work_minutes=net_work_minutes
    )

@app.route('/admin/users')
@admin_required
def admin_users():
    employees = Employee.query.all()
    return render_template('admin_users.html', employees=employees)

@app.route('/admin/logs/<int:user_id>')
@admin_required
def admin_logs(user_id):
    employee = Employee.query.get_or_404(user_id)
    records = Attendance.query.filter_by(employee_id=user_id).order_by(Attendance.timestamp.asc()).all()

    work_start = None
    break_start = None
    total_work = 0
    total_break = 0

    for r in records:
        if r.action_type == 'login':
            work_start = r.timestamp
        elif r.action_type == 'logout' and work_start:
            total_work += (r.timestamp - work_start).total_seconds()
            work_start = None
        elif r.action_type == 'break_start' and work_start:
            break_start = r.timestamp
        elif r.action_type == 'break_end' and break_start:
            total_break += (r.timestamp - break_start).total_seconds()
            break_start = None

    net_work = max(total_work - total_break, 0)

    work_hours = int(total_work // 3600)
    work_minutes = int((total_work % 3600) // 60)
    break_hours = int(total_break // 3600)
    break_minutes = int((total_break % 3600) // 60)
    net_work_hours = int(net_work // 3600)
    net_work_minutes = int((net_work % 3600) // 60)

    return render_template(
        'logs.html',
        records=records,
        name=employee.name,
        work_hours=work_hours,
        work_minutes=work_minutes,
        break_hours=break_hours,
        break_minutes=break_minutes,
        net_work_hours=net_work_hours,
        net_work_minutes=net_work_minutes
    )

# Create a sample user if not exists
with app.app_context():
    if not Employee.query.filter_by(email='jane.doe@example.com').first():
        sample_user = Employee(
            name='Jane Doe',
            email='jane.doe@example.com',
            password='password123',  # In production, hash this!
            role='employee'
        )
        db.session.add(sample_user)
        db.session.commit()
        print("Sample user 'Jane Doe' added successfully.")
    if not Employee.query.filter_by(email='admin@example.com').first():
        admin_user = Employee(
            name='Admin User',
            email='admin@example.com',
            password='adminpass',  # In production, hash this!
            role='admin'
        )
        db.session.add(admin_user)
        db.session.commit()
        print("Admin user 'Admin User' added successfully.")

if __name__ == '__main__':
    app.run(host='localhost', port=8080, debug=True)