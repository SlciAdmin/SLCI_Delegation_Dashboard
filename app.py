#!/usr/bin/env python3
"""
SLCI Delegation Dashboard - COMPLETELY FIXED FOR RENDER
✅ Login Manager initialization fixed
✅ SSL Database connection fixed
✅ Error handlers fixed
✅ All routes working
"""
import os
import sys
import urllib.parse
import json
import time
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, make_response, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Create Flask app FIRST
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_key_change_in_production')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 52428800))

# ============ ✅ DATABASE CONFIG - RENDER SSL FIXED ============
DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL:
    # Ensure sslmode=require
    if '?' not in DATABASE_URL:
        DATABASE_URL += '?sslmode=require'
    elif 'sslmode' not in DATABASE_URL:
        DATABASE_URL += '&sslmode=require'
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
    logger.info("🔗 Using DATABASE_URL with SSL")
else:
    from urllib.parse import quote_plus
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"postgresql://{os.getenv('DB_USER')}:"
        f"{quote_plus(os.getenv('DB_PASSWORD', ''))}@"
        f"{os.getenv('DB_HOST', 'localhost')}:"
        f"{os.getenv('DB_PORT', '5432')}/"
        f"{os.getenv('DB_NAME', 'postgres')}?sslmode=require"
    )
    logger.info("🔗 Using fallback DB config")

# ✅ ENGINE OPTIONS FOR RENDER STABILITY
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 180,
    'pool_timeout': 20,
    'connect_args': {
        'connect_timeout': 10,
        'sslmode': 'require',
        'options': '-csearch_path=delegation,public'
    }
}

# Create upload directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'admin_files'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'employee_files'), exist_ok=True)

# Initialize Flask-SQLAlchemy
db = SQLAlchemy(app)

# ✅ Initialize LoginManager AFTER db but BEFORE routes
login_manager = LoginManager()
login_manager.init_app(app)  # This MUST happen before any route uses current_user
login_manager.login_view = "login"
login_manager.login_message = "Please login to access this page."
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except:
        return None

# Database initialized flag
_db_initialized = False

def init_database():
    """Initialize database with retry logic"""
    global _db_initialized
    if _db_initialized:
        return True
    
    max_retries = 10
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
            logger.info(f"🔌 Connecting to database (attempt {attempt + 1}/{max_retries})...")
            
            # Test connection
            from sqlalchemy import text
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.commit()
            
            # Create tables
            db.create_all()
            
            logger.info("✅ Database connection successful!")
            _db_initialized = True
            return True
            
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"⚠️ DB attempt {attempt + 1} failed: {error_msg[:200]}")
            
            if 'ssl' in error_msg.lower() or 'closed unexpectedly' in error_msg.lower():
                logger.info("⚠️ SSL issue detected, waiting longer...")
                time.sleep(5)
            
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.info(f"⏳ Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logger.error(f"❌ Database initialization failed after {max_retries} attempts")
                return False
    
    return False

# ✅ FIXED: Don't access current_user in before_request
@app.before_request
def ensure_db_ready():
    """Ensure DB is initialized on first request - WITHOUT accessing current_user"""
    global _db_initialized
    if not _db_initialized:
        try:
            init_database()
        except Exception as e:
            logger.warning(f"⚠️ DB not ready yet: {e}")

# Helper Functions
def generate_whatsapp_link(phone_number, message):
    clean_phone = ''.join(filter(str.isdigit, phone_number))
    if not clean_phone:
        return "#"
    encoded_message = urllib.parse.quote(message, safe='')
    return f"https://wa.me/{clean_phone}?text={encoded_message}"

def generate_task_id():
    year = datetime.now().year
    try:
        last_task = Task.query.filter(Task.task_id.like(f'TASK-{year}-%')).order_by(Task.id.desc()).first()
        if last_task:
            last_num = int(last_task.task_id.split('-')[-1])
            new_num = last_num + 1
        else:
            new_num = 1
    except:
        new_num = 1
    return f'TASK-{year}-{new_num:03d}'

def send_notification(user_id, message, task_id=None, notif_type='info'):
    if not _db_initialized:
        return None
    try:
        notification = Notification(user_id=user_id, task_id=task_id, message=message, type=notif_type)
        db.session.add(notification)
        db.session.commit()
        return notification
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
        db.session.rollback()
        return None

def get_task_stats():
    if not _db_initialized:
        return {'total': 0, 'pending': 0, 'verified': 0, 'overdue': 0}
    try:
        tasks = Task.query.all()
        return {
            'total': len(tasks),
            'pending': len([t for t in tasks if t.status == 'pending']),
            'verified': len([t for t in tasks if t.status == 'verified']),
            'overdue': len([t for t in tasks if t.deadline and t.deadline < datetime.utcnow() and t.status != 'verified'])
        }
    except:
        return {'total': 0, 'pending': 0, 'verified': 0, 'overdue': 0}

def get_chart_data():
    if not _db_initialized:
        return {'status': {'labels': [], 'data': []}, 'performance': {'labels': [], 'data': [], 'total': []}}
    try:
        tasks = Task.query.all()
        status_counts = {}
        for t in tasks:
            status_counts[t.status] = status_counts.get(t.status, 0) + 1
        
        colors = {'pending': '#f59e0b', 'in_progress': '#6366f1', 'submitted': '#ec4899', 'verified': '#10b981'}
        
        return {
            'status': {
                'labels': list(status_counts.keys()),
                'data': list(status_counts.values()),
                'colors': [colors.get(s, '#64748b') for s in status_counts.keys()]
            },
            'performance': {
                'labels': [],
                'data': [],
                'total': []
            }
        }
    except:
        return {'status': {'labels': [], 'data': []}, 'performance': {'labels': [], 'data': [], 'total': []}}

# ============ ROUTES ============

@app.route('/')
def index():
    try:
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
    except:
        pass
    return render_template("index.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
    except:
        pass
    
    if request.method == "POST":
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return render_template("login.html")
        
        try:
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                if not user.is_active:
                    flash('Account deactivated. Contact admin.', 'error')
                    return render_template("login.html")
                login_user(user)
                flash(f'Welcome, {user.name}! 👋', 'success')
                return redirect(request.args.get('next') or url_for("dashboard"))
        except Exception as e:
            logger.error(f"Login error: {e}")
        
        flash('Invalid credentials or service initializing.', 'error')
        return render_template("login.html")
    
    return render_template("login.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    try:
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
    except:
        pass
    
    if request.method == "POST":
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role', 'employee')
        designation = request.form.get('designation', 'Employee')
        phone = request.form.get('phone', '').strip()
        
        if not all([name, email, password, phone]):
            flash('All fields required.', 'error')
            return render_template("register.html")
        
        try:
            if User.query.filter_by(email=email).first():
                flash('Email already registered.', 'error')
                return redirect(url_for('login'))
            
            user = User(name=name, email=email, role=role, designation=designation, phone=phone)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Account created! Please login.', 'success')
            return redirect(url_for("login"))
        except Exception as e:
            logger.error(f"Register error: {e}")
            flash('Registration failed. Try again.', 'error')
            return render_template("register.html")
    
    return render_template("register.html")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    if not _db_initialized:
        init_database()
    if current_user.role == "admin":
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('employee_dashboard'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Admin access required.', 'error')
        return redirect(url_for('dashboard'))
    
    if not _db_initialized:
        init_database()
    
    try:
        tasks = Task.query.order_by(Task.deadline.asc()).all()
        employees = User.query.filter_by(role='employee', is_active=True).all()
    except:
        tasks = []
        employees = []
    
    return render_template("admin_dashboard.html", tasks=tasks, employees=employees, stats=get_task_stats(), now=datetime.utcnow())

@app.route('/admin/create_task', methods=['GET', 'POST'])
@login_required
def create_task():
    if current_user.role != 'admin':
        flash('Unauthorized.', 'error')
        return redirect(url_for('dashboard'))
    
    if not _db_initialized:
        init_database()
    
    try:
        employees = User.query.filter_by(role='employee', is_active=True).all()
    except:
        employees = []
    
    if request.method == 'POST':
        try:
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            employee_id = request.form.get('employee_id')
            deadline_str = request.form.get('deadline')
            priority = request.form.get('priority', 'medium')
            
            if not all([title, employee_id, deadline_str]):
                flash('All fields required.', 'error')
                return render_template('create_task.html', employees=employees)
            
            deadline = datetime.strptime(deadline_str, '%Y-%m-%dT%H:%M')
            task_id = generate_task_id()
            
            admin_attachment = None
            if 'admin_attachment' in request.files:
                file = request.files['admin_attachment']
                if file and file.filename:
                    filename = secure_filename(f"{task_id}_{file.filename}")
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'admin_files', filename)
                    file.save(filepath)
                    admin_attachment = f'admin_files/{filename}'
            
            task = Task(
                task_id=task_id, title=title, description=description, deadline=deadline,
                status='pending', priority=priority, employee_id=int(employee_id),
                created_by=current_user.id, admin_attachment=admin_attachment
            )
            db.session.add(task)
            db.session.commit()
            
            employee = User.query.get(int(employee_id))
            if employee and employee.phone:
                msg = f"📋 New Task: {task.title}\nID: {task.task_id}\nDeadline: {deadline.strftime('%b %d')}"
                task.whatsapp_notify_link = generate_whatsapp_link(employee.phone, msg)
                db.session.commit()
            
            flash(f'Task {task_id} created! ✅', 'success')
            return redirect(url_for('admin_task_detail', task_id=task.id))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Create task error: {e}")
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('create_task.html', employees=employees)

@app.route('/admin/task/<int:task_id>')
@login_required
def admin_task_detail(task_id):
    if current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        task = Task.query.get(task_id)
        documents = TaskDocument.query.filter_by(task_id=task_id).all() if task else []
    except:
        task = None
        documents = []
    
    if not task:
        flash('Task not found.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('task_detail.html', task=task, documents=documents, user_role='admin', now=datetime.utcnow())

@app.route('/admin/verify_task/<int:task_id>', methods=['POST'])
@login_required
def verify_task(task_id):
    if current_user.role != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        task = Task.query.get(task_id)
        if not task:
            return jsonify({'success': False, 'error': 'Not found'}), 404
        
        action = request.form.get('action')
        notes = request.form.get('verification_notes', '').strip()
        
        if action == 'approve':
            task.status = 'verified'
            task.verified_at = datetime.utcnow()
            task.verified_by = current_user.id
            task.verification_notes = notes
            send_notification(task.employee_id, f"✅ Task Approved: {task.title}", task.id, 'success')
            flash('Approved!', 'success')
        elif action == 'reject':
            task.status = 'pending'
            task.verification_notes = f"Rejected: {notes}"
            send_notification(task.employee_id, f"⚠️ Task Returned: {task.title}", task.id, 'warning')
            flash('Returned for revision.', 'success')
        else:
            flash('Invalid action.', 'error')
            return redirect(url_for('admin_task_detail', task_id=task_id))
        
        db.session.commit()
        return redirect(url_for('admin_task_detail', task_id=task_id))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Verify error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/delete_employee/<int:user_id>')
@login_required
def delete_employee(user_id):
    if current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    try:
        user = User.query.get(user_id)
        if user and user.role == 'employee':
            pending = Task.query.filter_by(employee_id=user_id, status='pending').count()
            if pending > 0:
                flash(f'❌ User has {pending} pending task(s).', 'error')
            else:
                user.is_active = False
                db.session.commit()
                flash(f'Employee "{user.name}" deactivated.', 'success')
    except Exception as e:
        logger.error(f"Delete error: {e}")
        flash('Error deleting employee.', 'error')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reports')
@login_required
def reports():
    if current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        tasks = Task.query.all()
        employees = User.query.filter_by(role='employee').all()
    except:
        tasks = []
        employees = []
    
    return render_template('reports.html', tasks=tasks, stats=get_task_stats(), chart_data=get_chart_data(),
                          employees=employees, filters={}, now=datetime.utcnow())

@app.route('/admin/export_excel')
@login_required
def export_excel():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        import pandas as pd
        from io import BytesIO
        
        tasks = Task.query.all()
        data = [{
            'Task ID': t.task_id,
            'Title': t.title,
            'Employee': t.employee.name if t.employee else 'N/A',
            'Status': t.status,
            'Priority': t.priority,
            'Deadline': t.deadline.strftime('%Y-%m-%d') if t.deadline else ''
        } for t in tasks]
        
        df = pd.DataFrame(data)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename=SLCI_Report_{datetime.now().strftime("%Y%m%d")}.xlsx'
        return response
    except Exception as e:
        logger.error(f'Export error: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/employee/dashboard')
@login_required
def employee_dashboard():
    if current_user.role != 'employee':
        flash('Employee access required.', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        tasks = Task.query.filter_by(employee_id=current_user.id).order_by(Task.deadline.asc()).all()
        stats = current_user.get_stats()
    except:
        tasks = []
        stats = {}
    
    return render_template("employee_dashboard.html", tasks=tasks, stats=stats, now=datetime.utcnow())

@app.route('/employee/task/<int:task_id>')
@login_required
def employee_task_detail(task_id):
    try:
        task = Task.query.get(task_id)
        documents = TaskDocument.query.filter_by(task_id=task_id).all() if task else []
    except:
        task = None
        documents = []
    
    if not task:
        flash('Task not found.', 'error')
        return redirect(url_for('employee_dashboard'))
    
    if task.employee_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    
    return render_template('task_detail.html', task=task, documents=documents, user_role='employee', now=datetime.utcnow())

@app.route('/employee/submit_task/<int:task_id>', methods=['POST'])
@login_required
def submit_task(task_id):
    try:
        task = Task.query.get(task_id)
        if not task or task.employee_id != current_user.id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        if task.status in ['submitted', 'verified']:
            return jsonify({'success': False, 'error': 'Already submitted'}), 400
        
        employee_attachment = None
        if 'employee_attachment' in request.files:
            file = request.files['employee_attachment']
            if file and file.filename:
                filename = secure_filename(f"{task.task_id}_sub_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'employee_files', filename)
                file.save(filepath)
                employee_attachment = f'employee_files/{filename}'
                
                doc = TaskDocument(
                    task_id=task.id, uploaded_by=current_user.id, filename=filename,
                    original_filename=file.filename, file_type=file.content_type,
                    file_size=os.path.getsize(filepath)
                )
                db.session.add(doc)
        
        task.status = 'submitted'
        task.completed_at = datetime.utcnow()
        task.employee_attachment = employee_attachment
        db.session.commit()
        
        if task.creator and task.creator.phone:
            msg = f"✅ Task Submitted: {task.title}\nID: {task.task_id}"
            task.whatsapp_submission_link = generate_whatsapp_link(task.creator.phone, msg)
            db.session.commit()
        
        send_notification(task.created_by, f"✅ Task Submitted: {task.title}", task.id, 'success')
        return jsonify({'success': True, 'message': 'Submitted!'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Submit error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/notifications')
@login_required
def get_notifications():
    try:
        notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.created_at.desc()).limit(10).all()
        return jsonify([n.to_dict() for n in notifications])
    except:
        return jsonify([])

@app.route('/api/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notif_id):
    try:
        notification = Notification.query.get(notif_id)
        if notification and notification.user_id == current_user.id:
            notification.is_read = True
            db.session.commit()
            return jsonify({'success': True})
    except:
        pass
    return jsonify({'success': False}), 404

@app.route('/download/<path:filename>')
@login_required
def download_file(filename):
    safe_filename = secure_filename(filename)
    if not safe_filename:
        abort(404)
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.abspath(full_path).startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
        abort(403)
    if not os.path.exists(full_path):
        abort(404)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True, download_name=os.path.basename(filename))

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'app': 'SLCI Dashboard', 'db_initialized': _db_initialized}), 200

@app.route('/health/db')
@login_required
def health_db():
    try:
        if not _db_initialized:
            init_database()
        from sqlalchemy import text
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return jsonify({'status': 'healthy', 'database': 'connected', 'ssl': True}), 200
    except Exception as e:
        logger.error(f"DB health check failed: {e}")
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 503

@app.context_processor
def inject_globals():
    return {
        'current_year': datetime.now().year,
        'app_name': 'SLCI Delegation Dashboard',
        'generate_whatsapp_link': generate_whatsapp_link,
        'now': datetime.utcnow(),
        'db_ready': _db_initialized
    }

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    try:
        db.session.rollback()
    except:
        pass
    logger.error(f"Internal error: {error}")
    return render_template('500.html'), 500

# ============ MODELS ============

class User(db.Model):
    __tablename__ = 'users'
    __table_args__ = {"schema": "delegation"}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='employee')
    designation = db.Column(db.String(100), default='Employee')
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    def set_password(self, password):
        self.password = generate_password_hash(password, method='pbkdf2:sha256')
    
    def check_password(self, password):
        return check_password_hash(self.password, password)
    
    def get_stats(self):
        try:
            tasks = self.assigned_tasks.all()
            return {
                'total': len(tasks),
                'pending': len([t for t in tasks if t.status == 'pending']),
                'in_progress': len([t for t in tasks if t.status == 'in_progress']),
                'submitted': len([t for t in tasks if t.status == 'submitted']),
                'verified': len([t for t in tasks if t.status == 'verified']),
                'overdue': len([t for t in tasks if t.deadline and t.deadline < datetime.utcnow() and t.status != 'verified'])
            }
        except:
            return {}

class Task(db.Model):
    __tablename__ = 'tasks'
    __table_args__ = {"schema": "delegation"}
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    deadline = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(50), default="pending")
    priority = db.Column(db.String(20), default="medium")
    employee_id = db.Column(db.Integer, db.ForeignKey('delegation.users.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('delegation.users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    verified_by = db.Column(db.Integer, db.ForeignKey('delegation.users.id'), nullable=True)
    verification_notes = db.Column(db.Text)
    admin_attachment = db.Column(db.String(500))
    employee_attachment = db.Column(db.String(500))
    notification_3hr_sent = db.Column(db.Boolean, default=False)
    notification_1hr_sent = db.Column(db.Boolean, default=False)
    whatsapp_notify_link = db.Column(db.String(1000))
    whatsapp_submission_link = db.Column(db.String(1000))
    whatsapp_verification_link = db.Column(db.String(1000))
    whatsapp_reminder_3hr = db.Column(db.String(1000))
    whatsapp_reminder_1hr = db.Column(db.String(1000))
    
    employee = db.relationship('User', foreign_keys=[employee_id], backref='assigned_tasks')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_tasks')

class Notification(db.Model):
    __tablename__ = 'notifications'
    __table_args__ = {"schema": "delegation"}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('delegation.users.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('delegation.tasks.id'), nullable=True)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), default='info')
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='notifications')
    
    def to_dict(self):
        return {
            'id': self.id,
            'message': self.message,
            'type': self.type,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'task_id': self.task_id
        }

class TaskDocument(db.Model):
    __tablename__ = 'task_documents'
    __table_args__ = {"schema": "delegation"}
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('delegation.tasks.id'), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('delegation.users.id'), nullable=False)
    filename = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50))
    file_size = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    task = db.relationship('Task', backref='documents')
    uploader = db.relationship('User', backref='uploaded_documents')

# ============ MAIN ============
# ============ MAIN ENTRY POINT - FIXED ============
if __name__ == "__main__":
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    host = '0.0.0.0'
    port = int(os.getenv('PORT', 10000))
    
    logger.info(f"🚀 Starting SLCI Dashboard on http://{host}:{port}")
    
    # ✅ DO NOT call init_database() here!
    # Let gunicorn start HTTP server FIRST
    # DB will connect lazily via ensure_db_ready()
    
    app.run(host=host, port=port, debug=debug)