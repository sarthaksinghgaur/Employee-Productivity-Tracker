from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort
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
    return redirect(url_for('index'))

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
    app.run(debug=True)
    