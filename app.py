from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

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

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    action_type = db.Column(db.String(20))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Create DB tables
with app.app_context():
    db.create_all()

# Routes
@app.route('/')
def index():
    if 'employee_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']
    employee = Employee.query.filter_by(email=email, password=password).first()
    if employee:
        session['employee_id'] = employee.id
        session['employee_name'] = employee.name
        return redirect(url_for('dashboard'))
    return 'Invalid credentials', 401

@app.route('/dashboard')
def dashboard():
    if 'employee_id' not in session:
        return redirect(url_for('index'))
    return render_template('dashboard.html', name=session['employee_name'])

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

# Optional: View daily logs
@app.route('/attendance')
def view_attendance():
    if 'employee_id' not in session:
        return redirect(url_for('index'))
    records = Attendance.query.filter_by(employee_id=session['employee_id']).all()
    return render_template('logs.html', records=records)

if __name__ == '__main__':
    app.run(debug=True)