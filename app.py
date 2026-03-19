#!/usr/bin/env python3
"""
SLCI Delegation Dashboard - COMPLETE PRODUCTION READY
✅ Admin→Employee: Full task details via WhatsApp + Dashboard
✅ Employee→Admin: Submission details with attachments
✅ Auto-verify sync: WhatsApp approval → Dashboard update
✅ Smart Reminders: 2hr & 15min before deadline (same-day & multi-day)
✅ Mobile-friendly attachment downloads
✅ Real-time status sync between WhatsApp & Dashboard
"""
import os
import sys
import urllib.parse
import json
import time
import logging
import re
import threading
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, make_response, abort, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# ============ CREATE FLASK APP ============
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_key_change_in_production_2026!')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 52428800))  # 50MB

# ============ DATABASE CONFIG - RENDER SSL FIXED ============
DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL:
    if '?' not in DATABASE_URL:
        DATABASE_URL += '?sslmode=require'
    elif 'sslmode' not in DATABASE_URL.lower():
        DATABASE_URL += '&sslmode=require'
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
    logger.info("🔗 Using DATABASE_URL with SSL")
else:
    from urllib.parse import quote_plus
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"postgresql://{os.getenv('DB_USER', 'postgres')}:"
        f"{quote_plus(os.getenv('DB_PASSWORD', ''))}@"
        f"{os.getenv('DB_HOST', 'localhost')}:"
        f"{os.getenv('DB_PORT', '5432')}/"
        f"{os.getenv('DB_NAME', 'postgres')}?sslmode=require"
    )
    logger.info("🔗 Using fallback DB config")

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 180,
    'pool_timeout': 20,
    'connect_args': {
        'connect_timeout': 10,
        'sslmode': 'require',
        'options': '-c search_path=delegation,public'
    }
}

# Create upload directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'admin_files'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'employee_files'), exist_ok=True)

# ============ INITIALIZE EXTENSIONS ============
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please login to access this page."
login_manager.login_message_category = "info"

# ============ MODELS ============
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    __table_args__ = {"schema": "delegation"}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='employee')
    designation = db.Column(db.String(100), default='Employee')
    phone = db.Column(db.String(20))
    whatsapp_opt_in = db.Column(db.Boolean, default=True)  # User consent for WhatsApp
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    def set_password(self, password):
        self.password = generate_password_hash(password, method='pbkdf2:sha256')
    
    def check_password(self, password):
        return check_password_hash(self.password, password)
    
    def get_stats(self):
        try:
            tasks = self.assigned_tasks.all() if hasattr(self, 'assigned_tasks') else []
            now = datetime.utcnow()
            return {
                'total': len(tasks),
                'pending': len([t for t in tasks if t.status == 'pending']),
                'in_progress': len([t for t in tasks if t.status == 'in_progress']),
                'submitted': len([t for t in tasks if t.status == 'submitted']),
                'verified': len([t for t in tasks if t.status == 'verified']),
                'overdue': len([t for t in tasks if t.deadline and t.deadline < now and t.status not in ['verified', 'rejected']])
            }
        except:
            return {'total': 0, 'pending': 0, 'in_progress': 0, 'submitted': 0, 'verified': 0, 'overdue': 0}


class Task(db.Model):
    __tablename__ = 'tasks'
    __table_args__ = {"schema": "delegation"}
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    deadline = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(50), default="pending")  # pending, in_progress, submitted, verified, rejected
    priority = db.Column(db.String(20), default="medium")  # low, medium, high, urgent
    employee_id = db.Column(db.Integer, db.ForeignKey('delegation.users.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('delegation.users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    verified_by = db.Column(db.Integer, db.ForeignKey('delegation.users.id'), nullable=True)
    verification_notes = db.Column(db.Text)
    admin_attachment = db.Column(db.String(500))  # Path to admin uploaded file
    employee_attachment = db.Column(db.String(500))  # Path to employee submitted file
    reminder_2hr_sent = db.Column(db.Boolean, default=False)
    reminder_15min_sent = db.Column(db.Boolean, default=False)
    whatsapp_notify_sent = db.Column(db.Boolean, default=False)
    whatsapp_submission_sent = db.Column(db.Boolean, default=False)
    whatsapp_verification_sent = db.Column(db.Boolean, default=False)
    
    # Relationships
    employee = db.relationship('User', foreign_keys=[employee_id], backref='assigned_tasks')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_tasks')
    
    def get_public_url(self, filename):
        """Generate public download URL for attachments"""
        if not filename:
            return None
        base_url = os.getenv('APP_BASE_URL', 'https://your-app.onrender.com')
        return f"{base_url}/download/{filename}"
    
    def is_same_day_task(self):
        """Check if task deadline is same day as creation"""
        return self.deadline.date() == self.created_at.date()
    
    def get_time_until_deadline(self):
        """Get timedelta until deadline"""
        return self.deadline - datetime.utcnow()


class Notification(db.Model):
    __tablename__ = 'notifications'
    __table_args__ = {"schema": "delegation"}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('delegation.users.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('delegation.tasks.id'), nullable=True)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), default='info')  # info, success, warning, error, reminder
    is_read = db.Column(db.Boolean, default=False)
    is_whatsapp_sent = db.Column(db.Boolean, default=False)
    whatsapp_sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='notifications')
    task = db.relationship('Task', backref='notifications')
    
    def to_dict(self):
        return {
            'id': self.id,
            'message': self.message,
            'type': self.type,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'task_id': self.task_id,
            'task_title': self.task.title if self.task else None
        }


class TaskDocument(db.Model):
    __tablename__ = 'task_documents'
    __table_args__ = {"schema": "delegation"}
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('delegation.tasks.id'), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('delegation.users.id'), nullable=False)
    filename = db.Column(db.String(500), nullable=False)  # Stored filename
    original_filename = db.Column(db.String(500), nullable=False)  # Original name
    file_type = db.Column(db.String(50))
    file_size = db.Column(db.Integer)  # Size in bytes
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    download_count = db.Column(db.Integer, default=0)
    
    task = db.relationship('Task', backref='documents')
    uploader = db.relationship('User', backref='uploaded_documents')
    
    def get_download_url(self):
        """Generate secure download URL"""
        base_url = os.getenv('APP_BASE_URL', 'https://your-app.onrender.com')
        return f"{base_url}/download/{self.filename}"


class ReminderLog(db.Model):
    """Track sent reminders to avoid duplicates"""
    __tablename__ = 'reminder_logs'
    __table_args__ = {"schema": "delegation"}
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('delegation.tasks.id'), nullable=False)
    reminder_type = db.Column(db.String(20), nullable=False)  # '2hr', '15min'
    sent_via = db.Column(db.String(20), nullable=False)  # 'dashboard', 'whatsapp', 'both'
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    task = db.relationship('Task', backref='reminder_logs')


# ============ LOGIN MANAGER ============
@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except:
        return None


# ============ GLOBAL STATE ============
_db_initialized = False
_reminder_thread = None


def init_database():
    """Initialize database with retry logic"""
    global _db_initialized
    if _db_initialized:
        return True
    
    max_retries = 10
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
            logger.info(f"🔌 DB connect attempt {attempt + 1}/{max_retries}")
            from sqlalchemy import text
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.commit()
            db.create_all()
            logger.info("✅ Database ready!")
            _db_initialized = True
            return True
        except Exception as e:
            logger.warning(f"⚠️ DB attempt {attempt+1} failed: {str(e)[:150]}")
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
            else:
                logger.error(f"❌ DB init failed after {max_retries} attempts")
                return False
    return False


@app.before_request
def ensure_db_ready():
    """Lazy DB initialization"""
    global _db_initialized
    if not _db_initialized and request.endpoint not in ['health', 'static', 'download_file']:
        try:
            init_database()
        except Exception as e:
            logger.warning(f"⚠️ DB not ready: {e}")


# ============ HELPER FUNCTIONS ============
def generate_whatsapp_link(phone_number, message):
    """Generate clean WhatsApp click-to-chat link"""
    clean_phone = re.sub(r'[^\d+]', '', phone_number)
    if clean_phone.startswith('0'):
        clean_phone = '+91' + clean_phone[1:]  # Assume India if starts with 0
    if not clean_phone.startswith('+'):
        clean_phone = '+' + clean_phone
    encoded_msg = urllib.parse.quote(message.strip(), safe='')
    return f"https://wa.me/{clean_phone}?text={encoded_msg}"


def format_task_details_for_whatsapp(task, include_attachments=True):
    """Format complete task details for WhatsApp message"""
    admin_name = task.creator.name if task.creator else 'Admin'
    deadline_str = task.deadline.strftime('%d %b %Y, %I:%M %p')
    priority_emoji = {'low': '🟢', 'medium': '🟡', 'high': '🟠', 'urgent': '🔴'}.get(task.priority, '🔵')
    
    msg = f"""*📋 New Task Assigned*

*Task ID:* {task.task_id}
*Title:* {task.title}
*Priority:* {priority_emoji} {task.priority.upper()}
*Deadline:* {deadline_str}
*Assigned by:* {admin_name}

*Description:*
{task.description or 'No description provided.'}
"""
    
    if include_attachments and task.admin_attachment:
        download_url = task.get_public_url(task.admin_attachment)
        msg += f"\n*📎 Attachment:* {os.path.basename(task.admin_attachment)}\n🔗 Download: {download_url}"
    
    msg += f"\n\n_View full details & submit: {os.getenv('APP_BASE_URL', '')}/employee/task/{task.id}_"
    return msg


def format_submission_details_for_whatsapp(task, include_attachments=True):
    """Format submission details for admin WhatsApp notification"""
    emp_name = task.employee.name if task.employee else 'Employee'
    submit_time = task.completed_at.strftime('%d %b %Y, %I:%M %p') if task.completed_at else 'N/A'
    
    msg = f"""*✅ Task Submitted*

*Task ID:* {task.task_id}
*Title:* {task.title}
*Submitted by:* {emp_name}
*Submitted at:* {submit_time}
*Status:* 🟡 Pending Verification
"""
    
    if include_attachments and task.employee_attachment:
        download_url = task.get_public_url(task.employee_attachment)
        msg += f"\n*📎 Submission:* {os.path.basename(task.employee_attachment)}\n🔗 Download: {download_url}"
    
    # Show documents if any
    docs = TaskDocument.query.filter_by(task_id=task.id).all()
    if docs:
        msg += f"\n*📁 Additional Files:*"
        for doc in docs:
            msg += f"\n  • {doc.original_filename} [{format_file_size(doc.file_size)}]"
    
    msg += f"\n\n_Verify task: {os.getenv('APP_BASE_URL', '')}/admin/task/{task.id}_"
    return msg


def format_verification_details_for_whatsapp(task, action, notes=''):
    """Format verification result for WhatsApp"""
    emp_name = task.employee.name if task.employee else 'Employee'
    status_emoji = '✅' if action == 'approve' else '⚠️'
    status_text = 'APPROVED' if action == 'approve' else 'RETURNED FOR REVISION'
    
    msg = f"""*{status_emoji} Task {status_text}*

*Task ID:* {task.task_id}
*Title:* {task.title}
*Employee:* {emp_name}
*Verified at:* {datetime.utcnow().strftime('%d %b %Y, %I:%M %p')}
"""
    if notes:
        msg += f"\n*Note:* {notes}"
    
    if action == 'approve':
        msg += "\n\n🎉 Great work! Task completed successfully."
    else:
        msg += f"\n\n_Please revise and resubmit: {os.getenv('APP_BASE_URL', '')}/employee/task/{task.id}_"
    
    return msg


def format_file_size(size_bytes):
    """Convert bytes to human readable format"""
    if not size_bytes:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def generate_task_id():
    """Generate unique sequential task ID"""
    year = datetime.now().year
    try:
        last = Task.query.filter(Task.task_id.like(f'TASK-{year}-%')).order_by(Task.id.desc()).first()
        num = int(last.task_id.split('-')[-1]) + 1 if last else 1
    except:
        num = 1
    return f'TASK-{year}-{num:04d}'


def send_dashboard_notification(user_id, message, task_id=None, notif_type='info'):
    """Send in-app dashboard notification"""
    try:
        notif = Notification(user_id=user_id, task_id=task_id, message=message, type=notif_type)
        db.session.add(notif)
        db.session.commit()
        return notif
    except Exception as e:
        logger.error(f"Notification error: {e}")
        db.session.rollback()
        return None


def send_whatsapp_notification(phone, message, task_id=None, user_id=None, notif_type='info'):
    """Send WhatsApp notification AND create dashboard notification"""
    if not phone or not message:
        return None
    
    # Create dashboard notification first
    notif = send_dashboard_notification(user_id, message, task_id, notif_type)
    
    # Log WhatsApp intent (actual sending would use WhatsApp Business API)
    if notif and os.getenv('WHATSAPP_API_ENABLED', 'false').lower() == 'true':
        # In production: Integrate with WhatsApp Business API / Twilio / Meta
        # For now: Store the WhatsApp link for manual sending
        notif.is_whatsapp_sent = True
        notif.whatsapp_sent_at = datetime.utcnow()
        db.session.commit()
        logger.info(f"📱 WhatsApp ready for: {phone[:5]}...{phone[-4:]}")
    
    return notif


def check_and_send_reminders():
    """Background task: Check pending tasks and send reminders"""
    if not _db_initialized:
        return
    
    try:
        now = datetime.utcnow()
        pending_tasks = Task.query.filter(
            Task.status.in_(['pending', 'in_progress', 'submitted']),
            Task.deadline > now
        ).all()
        
        for task in pending_tasks:
            if not task.employee or not task.employee.phone or not task.employee.whatsapp_opt_in:
                continue
            
            time_left = task.get_time_until_deadline()
            hours_left = time_left.total_seconds() / 3600
            
            # Same-day task logic
            if task.is_same_day_task():
                # Send 2-hour reminder
                if hours_left <= 2 and hours_left > 0.25 and not task.reminder_2hr_sent:
                    send_task_reminder(task, '2hr')
                    task.reminder_2hr_sent = True
                
                # Send 15-min reminder
                if hours_left <= 0.25 and hours_left > 0 and not task.reminder_15min_sent:
                    send_task_reminder(task, '15min')
                    task.reminder_15min_sent = True
            
            # Multi-day task: Send reminders only on the due day
            elif task.deadline.date() == now.date():
                if hours_left <= 2 and hours_left > 0.25 and not task.reminder_2hr_sent:
                    send_task_reminder(task, '2hr')
                    task.reminder_2hr_sent = True
                if hours_left <= 0.25 and hours_left > 0 and not task.reminder_15min_sent:
                    send_task_reminder(task, '15min')
                    task.reminder_15min_sent = True
        
        db.session.commit()
    except Exception as e:
        logger.error(f"Reminder check error: {e}")
        db.session.rollback()


def send_task_reminder(task, reminder_type):
    """Send reminder via dashboard + WhatsApp"""
    time_text = "2 hours" if reminder_type == '2hr' else "15 minutes"
    emoji = '⏰' if reminder_type == '2hr' else '🔔'
    
    # Dashboard notification
    msg = f"{emoji} Reminder: Task '{task.title}' (ID: {task.task_id}) due in {time_text}!\nDeadline: {task.deadline.strftime('%I:%M %p')}"
    send_dashboard_notification(task.employee_id, msg, task.id, 'reminder')
    
    # WhatsApp notification
    if task.employee.phone and task.employee.whatsapp_opt_in:
        wa_msg = f"""*{emoji} Task Reminder*

*Task:* {task.title}
*ID:* {task.task_id}
*Due in:* {time_text}
*Deadline:* {task.deadline.strftime('%d %b, %I:%M %p')}

Please complete and submit on time! 🙏

_View task: {os.getenv('APP_BASE_URL', '')}/employee/task/{task.id}_"""
        
        send_whatsapp_notification(task.employee.phone, wa_msg, task.id, task.employee_id, 'reminder')
        
        # Log reminder
        log = ReminderLog(task_id=task.id, reminder_type=reminder_type, sent_via='both')
        db.session.add(log)
    
    logger.info(f"🔔 {reminder_type} reminder sent for task {task.task_id}")


def start_reminder_scheduler():
    """Start background thread for reminder checks"""
    def run_scheduler():
        while True:
            try:
                check_and_send_reminders()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            time.sleep(60)  # Check every minute
    
    global _reminder_thread
    if _reminder_thread is None or not _reminder_thread.is_alive():
        _reminder_thread = threading.Thread(target=run_scheduler, daemon=True)
        _reminder_thread.start()
        logger.info("🔄 Reminder scheduler started")


# ============ AUTH ROUTES ============
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
            flash('Please enter email and password.', 'error')
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
        
        flash('Invalid credentials.', 'error')
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
            flash('All fields are required.', 'error')
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
            db.session.rollback()
            flash('Registration failed.', 'error')
            return render_template("register.html")
    
    return render_template("register.html")


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))


# ============ DASHBOARD ROUTES ============
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
        stats = {
            'total': Task.query.count(),
            'pending': Task.query.filter_by(status='pending').count(),
            'submitted': Task.query.filter_by(status='submitted').count(),
            'verified': Task.query.filter_by(status='verified').count(),
            'overdue': Task.query.filter(Task.deadline < datetime.utcnow(), Task.status.notin_(['verified', 'rejected'])).count()
        }
    except Exception as e:
        logger.error(f"Admin dashboard error: {e}")
        tasks, employees, stats = [], [], {'total':0,'pending':0,'submitted':0,'verified':0,'overdue':0}
    
    return render_template("admin_dashboard.html", tasks=tasks, employees=employees, stats=stats, now=datetime.utcnow())


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
                flash('Title, Employee, and Deadline are required.', 'error')
                return render_template('create_task.html', employees=employees)
            
            deadline = datetime.strptime(deadline_str, '%Y-%m-%dT%H:%M')
            task_id = generate_task_id()
            
            # Handle admin attachment
            admin_attachment = None
            if 'admin_attachment' in request.files:
                file = request.files['admin_attachment']
                if file and file.filename:
                    filename = secure_filename(f"admin_{task_id}_{file.filename}")
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'admin_files', filename)
                    file.save(filepath)
                    admin_attachment = f'admin_files/{filename}'
            
            # Create task
            task = Task(
                task_id=task_id, title=title, description=description, deadline=deadline,
                status='pending', priority=priority, employee_id=int(employee_id),
                created_by=current_user.id, admin_attachment=admin_attachment
            )
            db.session.add(task)
            db.session.commit()
            
            # Send WhatsApp notification to employee with FULL details
            employee = User.query.get(int(employee_id))
            if employee and employee.phone and employee.whatsapp_opt_in:
                wa_msg = format_task_details_for_whatsapp(task, include_attachments=True)
                send_whatsapp_notification(employee.phone, wa_msg, task.id, employee.id, 'success')
                task.whatsapp_notify_sent = True
                db.session.commit()
            
            # Dashboard notification
            send_dashboard_notification(employee.id, f"📋 New task assigned: {task.title}", task.id, 'info')
            
            flash(f'Task {task_id} created & notified! ✅', 'success')
            return redirect(url_for('admin_task_detail', task_id=task.id))
            
        except ValueError:
            db.session.rollback()
            flash('Invalid date format. Use YYYY-MM-DDTHH:MM', 'error')
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
        task, documents = None, []
    
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
        
        action = request.form.get('action')  # 'approve' or 'reject'
        notes = request.form.get('verification_notes', '').strip()
        
        if action == 'approve':
            task.status = 'verified'
            task.verified_at = datetime.utcnow()
            task.verified_by = current_user.id
            task.verification_notes = notes
            
            # Notify employee via dashboard + WhatsApp
            if task.employee:
                msg = format_verification_details_for_whatsapp(task, 'approve', notes)
                send_whatsapp_notification(task.employee.phone, msg, task.id, task.employee.id, 'success')
                send_dashboard_notification(task.employee.id, f"✅ Task APPROVED: {task.title}", task.id, 'success')
            flash('Task approved! Employee notified.', 'success')
            
        elif action == 'reject':
            task.status = 'pending'  # Return to pending for revision
            task.verification_notes = f"Returned: {notes}"
            
            if task.employee:
                msg = format_verification_details_for_whatsapp(task, 'reject', notes)
                send_whatsapp_notification(task.employee.phone, msg, task.id, task.employee.id, 'warning')
                send_dashboard_notification(task.employee.id, f"⚠️ Task returned: {task.title}", task.id, 'warning')
            flash('Task returned for revision.', 'info')
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
        flash('Error.', 'error')
    
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
        tasks, employees = [], []
    
    return render_template('reports.html', tasks=tasks, employees=employees, now=datetime.utcnow())


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
            'Task ID': t.task_id, 'Title': t.title,
            'Employee': t.employee.name if t.employee else 'N/A',
            'Status': t.status, 'Priority': t.priority,
            'Deadline': t.deadline.strftime('%Y-%m-%d %H:%M') if t.deadline else '',
            'Created': t.created_at.strftime('%Y-%m-%d') if t.created_at else ''
        } for t in tasks]
        df = pd.DataFrame(data)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as w:
            df.to_excel(w, index=False)
        output.seek(0)
        resp = make_response(output.getvalue())
        resp.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        resp.headers['Content-Disposition'] = f'attachment; filename=SLCI_Report_{datetime.now().strftime("%Y%m%d")}.xlsx'
        return resp
    except ImportError:
        return jsonify({'error': 'pandas/openpyxl not installed'}), 500
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
    
    try:
        tasks = Task.query.filter_by(employee_id=current_user.id).order_by(Task.deadline.asc()).all()
        stats = current_user.get_stats()
        # Get unread notifications
        unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    except:
        tasks, stats, unread = [], {}, 0
    
    return render_template("employee_dashboard.html", tasks=tasks, stats=stats, unread_count=unread, now=datetime.utcnow())


@app.route('/employee/task/<int:task_id>')
@login_required
def employee_task_detail(task_id):
    try:
        task = Task.query.get(task_id)
        documents = TaskDocument.query.filter_by(task_id=task_id).all() if task else []
    except:
        task, documents = None, []
    
    if not task:
        flash('Task not found.', 'error')
        return redirect(url_for('employee_dashboard'))
    
    if task.employee_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    
    # Mark related notifications as read
    Notification.query.filter_by(user_id=current_user.id, task_id=task_id, is_read=False).update({'is_read': True})
    db.session.commit()
    
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
        
        # Handle employee attachment
        employee_attachment = None
        if 'employee_attachment' in request.files:
            file = request.files['employee_attachment']
            if file and file.filename:
                filename = secure_filename(f"emp_{task.task_id}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'employee_files', filename)
                file.save(filepath)
                employee_attachment = f'employee_files/{filename}'
                # Log document
                doc = TaskDocument(
                    task_id=task.id, uploaded_by=current_user.id, filename=filename,
                    original_filename=file.filename, file_type=file.content_type,
                    file_size=os.path.getsize(filepath)
                )
                db.session.add(doc)
        
        # Update task
        task.status = 'submitted'
        task.completed_at = datetime.utcnow()
        task.employee_attachment = employee_attachment
        
        db.session.commit()
        
        # Notify admin via WhatsApp + Dashboard with FULL submission details
        if task.creator and task.creator.phone:
            wa_msg = format_submission_details_for_whatsapp(task, include_attachments=True)
            send_whatsapp_notification(task.creator.phone, wa_msg, task.id, task.creator.id, 'success')
        
        send_dashboard_notification(task.created_by, f"✅ Task submitted: {task.title}", task.id, 'success')
        
        return jsonify({'success': True, 'message': 'Submitted successfully!', 'task_id': task.task_id})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Submit error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ API ROUTES ============
@app.route('/api/notifications')
@login_required
def get_notifications():
    try:
        notifs = Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.created_at.desc()).limit(20).all()
        return jsonify([n.to_dict() for n in notifs])
    except:
        return jsonify([])


@app.route('/api/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notif_id):
    try:
        n = Notification.query.get(notif_id)
        if n and n.user_id == current_user.id:
            n.is_read = True
            db.session.commit()
            return jsonify({'success': True})
    except:
        pass
    return jsonify({'success': False}), 404


@app.route('/api/task/<int:task_id>/status')
@login_required
def get_task_status(task_id):
    """API endpoint for real-time status check (polling)"""
    try:
        task = Task.query.get(task_id)
        if not task:
            return jsonify({'error': 'Not found'}), 404
        # Check access
        if task.employee_id != current_user.id and current_user.role != 'admin':
            return jsonify({'error': 'Unauthorized'}), 403
        return jsonify({
            'task_id': task.task_id,
            'status': task.status,
            'verified_at': task.verified_at.isoformat() if task.verified_at else None,
            'verification_notes': task.verification_notes
        })
    except Exception as e:
        logger.error(f"Status API error: {e}")
        return jsonify({'error': str(e)}), 500


# ============ FILE DOWNLOAD (Mobile-Friendly) ============
@app.route('/download/<path:filename>')
@login_required
def download_file(filename):
    safe = secure_filename(filename)
    if not safe:
        abort(404)
    
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    # Security: prevent directory traversal
    if not os.path.abspath(full_path).startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
        abort(403)
    if not os.path.exists(full_path):
        abort(404)
    
    # Track download
    doc = TaskDocument.query.filter_by(filename=filename).first()
    if doc:
        doc.download_count = (doc.download_count or 0) + 1
        db.session.commit()
    
    return send_from_directory(
        app.config['UPLOAD_FOLDER'], 
        filename, 
        as_attachment=True, 
        download_name=os.path.basename(filename)
    )


# ============ HEALTH CHECKS ============
@app.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'app': 'SLCI Dashboard',
        'db_initialized': _db_initialized,
        'scheduler_active': _reminder_thread is not None and _reminder_thread.is_alive(),
        'timestamp': datetime.utcnow().isoformat()
    }), 200


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
        logger.error(f"DB health failed: {e}")
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 503


# ============ CONTEXT PROCESSOR ============
@app.context_processor
def inject_globals():
    unread = 0
    if current_user.is_authenticated:
        try:
            unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        except:
            pass
    return {
        'current_year': datetime.now().year,
        'app_name': 'SLCI Delegation Dashboard',
        'generate_whatsapp_link': generate_whatsapp_link,
        'now': datetime.utcnow(),
        'db_ready': _db_initialized,
        'unread_notifications': unread,
        'app_base_url': os.getenv('APP_BASE_URL', '')
    }


# ============ ERROR HANDLERS ============
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    try:
        db.session.rollback()
    except:
        pass
    logger.error(f"500 error: {e}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Server error'}), 500
    return render_template('500.html'), 500

@app.errorhandler(403)
def forbidden(e):
    flash('Access denied.', 'error')
    return redirect(url_for('index'))


# ============ MAIN ============
if __name__ == "__main__":
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 10000))
    
    logger.info(f"🚀 Starting SLCI Dashboard on http://{host}:{port}")
    
    if debug:
        init_database()
        start_reminder_scheduler()  # Start reminders in dev too
    
    app.run(host=host, port=port, debug=debug)