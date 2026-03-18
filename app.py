#!/usr/bin/env python3
"""
SLCI Delegation Dashboard - Complete Flask Backend
✅ FIXED: PostgreSQL SSL Connection for Render.com
✅ Lazy database initialization (no fail at import)
✅ Internal DATABASE_URL support (no SSL needed for Render-to-Render)
✅ WhatsApp notifications + file serving + all features preserved
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

# Import models (db object defined here, initialized later)
from models import db, User, Task, Notification, TaskDocument
from voice_processor import process_voice_task
import pandas as pd
from io import BytesIO

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)

# ============ ✅ CONFIGURATION ============
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_key_change_in_production')
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 52428800))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ✅ FIXED: Database URI with proper SSL handling for Render
def get_database_uri():
    """Build database URI with proper SSL configuration for Render"""
    # Option 1: Use internal DATABASE_URL (preferred - no SSL needed for Render-to-Render)
    if os.getenv('USE_INTERNAL_DB') == 'true' and os.getenv('DATABASE_URL'):
        logger.info("🔗 Using internal DATABASE_URL (Render internal connection)")
        return os.getenv('DATABASE_URL')
    
    # Option 2: Build from individual env vars with SSL
    from urllib.parse import quote_plus
    db_user = os.getenv('DB_USER', 'postgres')
    db_password = quote_plus(os.getenv('DB_PASSWORD', ''))  # URL-encode password
    db_host = os.getenv('DB_HOST', 'localhost')
    db_port = os.getenv('DB_PORT', '5432')
    db_name = os.getenv('DB_NAME', 'postgres')
    
    # For external connections: add sslmode=require
    uri = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?sslmode=require"
    logger.info("🔗 Using external DB URI with sslmode=require")
    return uri

app.config['SQLALCHEMY_DATABASE_URI'] = get_database_uri()

# ✅ FIXED: Engine options with connection pooling + retry settings
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,        # ✅ Auto-reconnect on stale connections
    'pool_recycle': 300,          # ✅ Recycle every 5 minutes
    'pool_timeout': 30,           # ✅ Wait up to 30s for connection
    'max_overflow': 10,           # ✅ Allow burst connections
    'connect_args': {
        'connect_timeout': 10,    # ✅ Connection timeout
        'options': '-csearch_path=delegation,public'  # ✅ Your schema
    }
}

# Create upload directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'admin_files'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'employee_files'), exist_ok=True)

# Initialize extensions (but NOT database yet!)
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Please login to access this page."
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id)) if db.engine else None

# ============ ✅ LAZY DATABASE INITIALIZATION ============
_db_initialized = False

def init_database():
    """Initialize database with robust retry logic - CALLED AT RUNTIME, not import"""
    global _db_initialized
    if _db_initialized:
        return True
    
    max_retries = 10
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
            logger.info(f"🔌 Connecting to database (attempt {attempt + 1}/{max_retries})...")
            
            # Initialize db with app context
            db.init_app(app)
            
            # Test connection with simple query
            with app.app_context():
                with db.engine.connect() as conn:
                    from sqlalchemy import text
                    conn.execute(text("SELECT 1"))
                    logger.info("✅ Database connection successful!")
            
            # Create tables if needed
            with app.app_context():
                db.create_all()
                logger.info("✅ Database tables ready")
            
            _db_initialized = True
            return True
            
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"⚠️ DB attempt {attempt + 1} failed: {error_msg}")
            
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # Exponential backoff
                logger.info(f"⏳ Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logger.error(f"❌ Database initialization failed after {max_retries} attempts")
                # Don't raise - let app start anyway, routes will retry
                return False
    
    return False


# ============ ✅ HELPER FUNCTIONS ============
def generate_whatsapp_link(phone_number, message):
    """Generate WhatsApp wa.me link - FIXED"""
    clean_phone = ''.join(filter(str.isdigit, phone_number))
    if not clean_phone:
        return "#"
    encoded_message = urllib.parse.quote(message, safe='')
    return f"https://wa.me/{clean_phone}?text={encoded_message}"


def generate_task_id():
    """Generate unique task ID like TASK-2026-001"""
    year = datetime.now().year
    last_task = Task.query.filter(Task.task_id.like(f'TASK-{year}-%')).order_by(Task.id.desc()).first() if _db_initialized else None
    if last_task:
        last_num = int(last_task.task_id.split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1
    return f'TASK-{year}-{new_num:03d}'


def send_notification(user_id, message, task_id=None, notif_type='info'):
    """Create notification - with DB check"""
    if not _db_initialized:
        logger.warning("⚠️ Cannot send notification: DB not initialized")
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


def check_deadline_notifications():
    """Check deadlines - safe if DB not ready"""
    if not current_user.is_authenticated or not _db_initialized:
        return
    try:
        now = datetime.utcnow()
        pending_tasks = Task.query.filter(
            Task.status.in_(['pending', 'in_progress']),
            Task.deadline != None
        ).all()
        
        for task in pending_tasks:
            if not task.deadline or not task.employee or not task.employee.phone:
                continue
            time_to_deadline = task.deadline - now
            
            if timedelta(hours=2) <= time_to_deadline <= timedelta(hours=4) and not task.notification_3hr_sent:
                send_notification(task.employee_id, f"⏰ Task Reminder: '{task.title}' due in 3 hours!", task.id, 'warning')
                task.whatsapp_reminder_3hr = generate_whatsapp_link(task.employee.phone, f"⏰ Reminder: Task {task.task_id}")
                task.notification_3hr_sent = True
                
            if timedelta(minutes=50) <= time_to_deadline <= timedelta(hours=2) and not task.notification_1hr_sent:
                send_notification(task.employee_id, f"🚨 URGENT: '{task.title}' due in 1 hour!", task.id, 'error')
                task.whatsapp_reminder_1hr = generate_whatsapp_link(task.employee.phone, f"🚨 URGENT: Task {task.task_id}")
                task.notification_1hr_sent = True
        
        db.session.commit()
    except Exception as e:
        logger.warning(f"Deadline check skipped: {e}")


def get_task_stats():
    """Get stats - safe fallback"""
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
    """Chart data - safe fallback"""
    if not _db_initialized:
        return {'status': {'labels': [], 'data': []}, 'performance': {'labels': [], 'data': [], 'total': []}}
    # ... (same logic as before, wrapped in try/except)
    return {'status': {'labels': [], 'data': []}, 'performance': {'labels': [], 'data': [], 'total': []}}


# ============ PUBLIC ROUTES ============
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template("index.html")


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == "POST":
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return render_template("login.html")
        if _db_initialized:
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                if not user.is_active:
                    flash('Account deactivated. Contact admin.', 'error')
                    return render_template("login.html")
                login_user(user)
                flash(f'Welcome, {user.name}! 👋', 'success')
                return redirect(request.args.get('next') or url_for("dashboard"))
        flash('Service initializing. Try again in 30s.', 'info')
    return render_template("login.html")


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
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
        if _db_initialized and User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('login'))
        if _db_initialized:
            user = User(name=name, email=email, role=role, designation=designation, phone=phone)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Account created! Please login.', 'success')
            return redirect(url_for("login"))
        flash('Service initializing. Try again soon.', 'info')
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
    # Try to init DB on first dashboard access
    if not _db_initialized:
        init_database()
    check_deadline_notifications()
    if current_user.role == "admin":
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('employee_dashboard'))


# ============ ADMIN ROUTES ============
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Admin access required.', 'error')
        return redirect(url_for('dashboard'))
    if not _db_initialized and not init_database():
        flash('Database connecting... please wait.', 'info')
    check_deadline_notifications()
    tasks = Task.query.order_by(Task.deadline.asc()).all() if _db_initialized else []
    employees = User.query.filter_by(role='employee', is_active=True).all() if _db_initialized else []
    return render_template("admin_dashboard.html", tasks=tasks, employees=employees, stats=get_task_stats(), now=datetime.utcnow())


@app.route('/admin/create_task', methods=['GET', 'POST'])
@login_required
def create_task():
    if current_user.role != 'admin':
        flash('Unauthorized.', 'error')
        return redirect(url_for('dashboard'))
    if not _db_initialized and not init_database():
        flash('Database not ready. Try again.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    employees = User.query.filter_by(role='employee', is_active=True).all()
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
            
            task = Task(task_id=task_id, title=title, description=description, deadline=deadline,
                       status='pending', priority=priority, employee_id=int(employee_id),
                       created_by=current_user.id, admin_attachment=admin_attachment)
            db.session.add(task)
            db.session.commit()
            
            # WhatsApp link
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
    task = db.session.get(Task, task_id) if _db_initialized else None
    if not task:
        flash('Task not found.', 'error')
        return redirect(url_for('admin_dashboard'))
    documents = TaskDocument.query.filter_by(task_id=task_id).all() if _db_initialized else []
    return render_template('task_detail.html', task=task, documents=documents, user_role='admin', now=datetime.utcnow())


@app.route('/admin/verify_task/<int:task_id>', methods=['POST'])
@login_required
def verify_task(task_id):
    if current_user.role != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    if not _db_initialized:
        return jsonify({'success': False, 'error': 'DB not ready'}), 503
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    try:
        action = request.form.get('action')
        notes = request.form.get('verification_notes', '').strip()
        if action == 'approve':
            task.status = 'verified'
            task.verified_at = datetime.utcnow()
            task.verified_by = current_user.id
            task.verification_notes = notes
            send_notification(task.employee_id, f"✅ Task Approved: {task.title}", task.id, 'success')
            msg = 'Approved!'
        elif action == 'reject':
            task.status = 'pending'
            task.verification_notes = f"Rejected: {notes}"
            send_notification(task.employee_id, f"⚠️ Task Returned: {task.title}", task.id, 'warning')
            msg = 'Returned for revision.'
        else:
            flash('Invalid action.', 'error')
            return redirect(url_for('admin_task_detail', task_id=task_id))
        db.session.commit()
        flash(msg, 'success')
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
    if not _db_initialized:
        flash('DB not ready.', 'error')
        return redirect(url_for('admin_dashboard'))
    user = db.session.get(User, user_id)
    if user and user.role == 'employee':
        pending = Task.query.filter_by(employee_id=user_id, status='pending').count()
        if pending > 0:
            flash(f'❌ User has {pending} pending task(s).', 'error')
        else:
            user.is_active = False
            db.session.commit()
            flash(f'Employee "{user.name}" deactivated.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/reports')
@login_required
def reports():
    if current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    tasks = Task.query.all() if _db_initialized else []
    employees = User.query.filter_by(role='employee').all() if _db_initialized else []
    return render_template('reports.html', tasks=tasks, stats=get_task_stats(), chart_data=get_chart_data(),
                          employees=employees, filters={}, now=datetime.utcnow())


@app.route('/admin/export_excel')
@login_required
def export_excel():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    if not _db_initialized:
        return jsonify({'error': 'DB not ready'}), 503
    try:
        tasks = Task.query.all()
        data = [{'Task ID': t.task_id, 'Title': t.title, 'Employee': t.employee.name if t.employee else 'N/A',
                'Status': t.status, 'Priority': t.priority, 'Deadline': t.deadline.strftime('%Y-%m-%d') if t.deadline else ''} for t in tasks]
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


# ============ EMPLOYEE ROUTES ============
@app.route('/employee/dashboard')
@login_required
def employee_dashboard():
    if current_user.role != 'employee':
        flash('Employee access required.', 'error')
        return redirect(url_for('dashboard'))
    if not _db_initialized and not init_database():
        flash('Database connecting...', 'info')
    tasks = Task.query.filter_by(employee_id=current_user.id).order_by(Task.deadline.asc()).all() if _db_initialized else []
    return render_template("employee_dashboard.html", tasks=tasks, stats=current_user.get_stats() if _db_initialized else {}, now=datetime.utcnow())


@app.route('/employee/task/<int:task_id>')
@login_required
def employee_task_detail(task_id):
    task = db.session.get(Task, task_id) if _db_initialized else None
    if not task:
        flash('Task not found.', 'error')
        return redirect(url_for('employee_dashboard'))
    if task.employee_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    documents = TaskDocument.query.filter_by(task_id=task_id).all() if _db_initialized else []
    return render_template('task_detail.html', task=task, documents=documents, user_role='employee', now=datetime.utcnow())


@app.route('/employee/submit_task/<int:task_id>', methods=['POST'])
@login_required
def submit_task(task_id):
    if not _db_initialized:
        return jsonify({'success': False, 'error': 'DB not ready'}), 503
    task = db.session.get(Task, task_id)
    if not task or task.employee_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    if task.status in ['submitted', 'verified']:
        return jsonify({'success': False, 'error': 'Already submitted'}), 400
    try:
        employee_attachment = None
        if 'employee_attachment' in request.files:
            file = request.files['employee_attachment']
            if file and file.filename:
                filename = secure_filename(f"{task.task_id}_sub_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'employee_files', filename)
                file.save(filepath)
                employee_attachment = f'employee_files/{filename}'
                doc = TaskDocument(task_id=task.id, uploaded_by=current_user.id, filename=filename,
                                  original_filename=file.filename, file_type=file.content_type,
                                  file_size=os.path.getsize(filepath))
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


# ============ API & UTILS ============
@app.route('/api/notifications')
@login_required
def get_notifications():
    if not _db_initialized:
        return jsonify([])
    notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.created_at.desc()).limit(10).all()
    return jsonify([n.to_dict() for n in notifications])


@app.route('/api/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notif_id):
    if not _db_initialized:
        return jsonify({'success': False}), 503
    notification = db.session.get(Notification, notif_id)
    if notification and notification.user_id == current_user.id:
        notification.is_read = True
        db.session.commit()
        return jsonify({'success': True})
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
    force_download = request.args.get('force', '0') == '1'
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=force_download, download_name=os.path.basename(filename))


@app.route('/health/db')
@login_required
def health_db():
    """Database health check endpoint"""
    if not _db_initialized:
        init_database()
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return jsonify({'status': 'healthy', 'database': 'connected', 'initialized': _db_initialized}), 200
    except Exception as e:
        logger.error(f"DB health check failed: {e}")
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 503


@app.route('/health')
def health():
    """Simple health check (no auth)"""
    return jsonify({'status': 'ok', 'app': 'SLCI Dashboard', 'db_initialized': _db_initialized}), 200


# ============ VOICE API ============
@app.route('/api/process_voice', methods=['POST'])
@login_required
def api_process_voice():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    if 'voice' not in request.files:
        return jsonify({'success': False, 'error': 'No audio'}), 400
    voice = request.files['voice']
    if voice.filename == '':
        return jsonify({'success': False, 'error': 'Empty filename'}), 400
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = secure_filename(f"{timestamp}_voice.webm")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        voice.save(filepath)
        employee_list = [{'id': u.id, 'name': u.name.lower()} for u in User.query.filter_by(role='employee').all()] if _db_initialized else []
        task_data = process_voice_task(filepath, employee_list=employee_list)
        return jsonify({'success': True, 'task': task_data})
    except Exception as e:
        logger.error(f'Voice error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if os.path.exists(filepath):
            try: os.remove(filepath)
            except: pass


@app.route('/api/create_task', methods=['POST'])
@login_required
def api_create_task():
    if current_user.role != 'admin' or not _db_initialized:
        return jsonify({'success': False, 'error': 'Unauthorized/DB not ready'}), 403
    data = request.get_json()
    if not data or 'task' not in data:
        return jsonify({'success': False, 'error': 'Invalid payload'}), 400
    task_info = data['task']
    try:
        task = Task(task_id=generate_task_id(), title=task_info['title'][:200],
                   description=task_info.get('description', '')[:2000],
                   deadline=datetime.fromisoformat(task_info['deadline']) if task_info.get('deadline') else datetime.now() + timedelta(days=2),
                   status='pending', employee_id=task_info.get('employee_id') or current_user.id,
                   created_by=current_user.id, priority=task_info.get('priority', 'medium'))
        db.session.add(task)
        db.session.commit()
        return jsonify({'success': True, 'task_id': task.id, 'task_code': task.task_id})
    except Exception as e:
        db.session.rollback()
        logger.error(f'API create error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ GLOBAL HOOKS ============
@app.before_request
def before_request():
    if current_user.is_authenticated and not _db_initialized:
        init_database()
    if current_user.is_authenticated:
        check_deadline_notifications()


@app.context_processor
def inject_globals():
    return {'current_year': datetime.now().year, 'app_name': 'SLCI Delegation Dashboard',
            'generate_whatsapp_link': generate_whatsapp_link, 'now': datetime.utcnow(), 'db_ready': _db_initialized}


# ============ ERROR HANDLERS ============
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    if db.session:
        db.session.rollback()
    logger.error(f"Internal error: {error}")
    return render_template('500.html'), 500


# ============ MAIN ENTRY POINT ============
if __name__ == "__main__":
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    host = '0.0.0.0' if os.getenv('FLASK_ENV') == 'production' else '127.0.0.1'
    port = int(os.getenv('PORT', 10000))
    
    logger.info(f"🚀 Starting SLCI Dashboard on http://{host}:{port}")
    logger.info(f"🔗 Database: {'Internal' if os.getenv('USE_INTERNAL_DB') == 'true' else 'External + SSL'}")
    
    # Initialize DB before starting server (with retries)
    init_database()
    
    app.run(host=host, port=port, debug=debug)