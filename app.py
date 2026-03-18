#!/usr/bin/env python3
"""
SLCI Delegation Dashboard - Complete Flask Backend
✅ WhatsApp notifications with PREVIEW + DOWNLOAD links
✅ Full task details in messages
✅ Proper newline formatting for WhatsApp
✅ FIXED: URL path separator + WhatsApp link + file serving
"""
import os
import urllib.parse
import uuid
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, make_response, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from models import db, User, Task, Notification, TaskDocument
from voice_processor import process_voice_task
import pandas as pd
from io import BytesIO

load_dotenv()

app = Flask(__name__)

# ============ CONFIGURATION ============
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_key_change_in_production')
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"postgresql://{os.getenv('DB_USER', 'postgres')}:"
    f"{os.getenv('DB_PASSWORD', 'SLCI123')}@"
    f"{os.getenv('DB_HOST', 'localhost')}:"
    f"{os.getenv('DB_PORT', '5432')}/"
    f"{os.getenv('DB_NAME', 'Delegation_db')}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 52428800))

# Create upload directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'admin_files'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'employee_files'), exist_ok=True)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please login to access this page."
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Create tables
with app.app_context():
    db.create_all()

# ============ ✅ HELPER FUNCTIONS (FULLY FIXED) ============
def generate_whatsapp_link(phone_number, message):
    """Generates a wa.me link with pre-filled text - FULLY FIXED"""
    # Remove all non-digit characters from phone
    clean_phone = ''.join(filter(str.isdigit, phone_number))
    if not clean_phone:
        return "#"
    
    # ✅ Properly encode message for URL (handles newlines, special chars)
    encoded_message = urllib.parse.quote(message, safe='')
    
    # ✅ FIXED: Removed extra spaces in WhatsApp URL
    return f"https://wa.me/{clean_phone}?text={encoded_message}"

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "connect_args": {
        "options": "-csearch_path=delegation,public"
    }
}
def generate_task_id():
    """Generate unique task ID like TASK-2026-001"""
    year = datetime.now().year
    last_task = Task.query.filter(Task.task_id.like(f'TASK-{year}-%')).order_by(Task.id.desc()).first()
    if last_task:
        last_num = int(last_task.task_id.split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1
    return f'TASK-{year}-{new_num:03d}'


def send_notification(user_id, message, task_id=None, notif_type='info'):
    """Create and send a notification to a user"""
    notification = Notification(user_id=user_id, task_id=task_id, message=message, type=notif_type)
    db.session.add(notification)
    db.session.commit()
    return notification


def check_deadline_notifications():
    """Check for upcoming deadlines and send reminders"""
    if not current_user.is_authenticated:
        return
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
            send_notification(task.employee_id,
                f"⏰ Task Reminder: '{task.title}' is due in 3 hours!",
                task.id, 'warning')
            task.whatsapp_reminder_3hr = generate_whatsapp_link(
                task.employee.phone,
                f"⏰ Reminder: Task {task.task_id} - '{task.title}' Deadline: {task.deadline.strftime('%b %d, %Y %I:%M %p')} Priority: {task.priority.upper()} Please complete on time! ✅"
            )
            task.notification_3hr_sent = True
            
        if timedelta(minutes=50) <= time_to_deadline <= timedelta(hours=2) and not task.notification_1hr_sent:
            send_notification(task.employee_id,
                f"🚨 URGENT: '{task.title}' is due in 1 hour!",
                task.id, 'error')
            task.whatsapp_reminder_1hr = generate_whatsapp_link(
                task.employee.phone,
                f"🚨 URGENT: Task {task.task_id} - '{task.title}' ⏰ Due in 1 HOUR! Deadline: {task.deadline.strftime('%b %d, %I:%M %p')} Please submit immediately! ⚡"
            )
            task.notification_1hr_sent = True
    
    db.session.commit()


def get_task_stats():
    """Get aggregated task statistics for dashboard"""
    tasks = Task.query.all()
    total = len(tasks)
    pending = len([t for t in tasks if t.status == 'pending'])
    verified = len([t for t in tasks if t.status == 'verified'])
    overdue = len([t for t in tasks if t.deadline and t.deadline < datetime.utcnow() and t.status != 'verified'])
    return {'total': total, 'pending': pending, 'verified': verified, 'overdue': overdue}


def get_chart_data():
    """Prepare data for Chart.js visualizations"""
    tasks = Task.query.all()
    status_counts = {}
    for t in tasks:
        status_counts[t.status] = status_counts.get(t.status, 0) + 1
    
    emp_stats = {}
    for t in tasks:
        name = t.employee.name if t.employee else 'Unknown'
        if name not in emp_stats:
            emp_stats[name] = {'total': 0, 'on_time': 0}
        emp_stats[name]['total'] += 1
        if t.status == 'verified' and t.completed_at and t.deadline and t.completed_at <= t.deadline:
            emp_stats[name]['on_time'] += 1
    
    return {
        'status': {
            'labels': list(status_counts.keys()),
            'data': list(status_counts.values()),
            'colors': ['#f59e0b', '#10b981', '#6366f1', '#ec4899', '#ef4444']
        },
        'performance': {
            'labels': list(emp_stats.keys()),
            'data': [v['on_time'] for v in emp_stats.values()],
            'total': [v['total'] for v in emp_stats.values()]
        }
    }


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
        
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            if not user.is_active:
                flash('Account is deactivated. Please contact admin.', 'error')
                return render_template("login.html")
            login_user(user)
            flash(f'Welcome back, {user.name}! 👋', 'success')
            return redirect(request.args.get('next') or url_for("dashboard"))
        else:
            flash('Invalid email or password.', 'error')
    
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
            flash('All required fields must be filled.', 'error')
            return render_template("register.html")
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('login'))
        
        user = User(name=name, email=email, role=role, designation=designation, phone=phone)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for("login"))
    
    return render_template("register.html")


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))


# ============ MAIN DASHBOARD ROUTE ============
@app.route('/dashboard')
@login_required
def dashboard():
    check_deadline_notifications()
    if current_user.role == "admin":
        return redirect(url_for('admin_dashboard'))
    else:
        return redirect(url_for('employee_dashboard'))


# ============ ADMIN DASHBOARD ============
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))
    
    check_deadline_notifications()
    tasks = Task.query.order_by(Task.deadline.asc(), Task.created_at.desc()).all()
    employees = User.query.filter_by(role='employee', is_active=True).all()
    stats = get_task_stats()
    
    return render_template(
        "admin_dashboard.html",
        tasks=tasks,
        employees=employees,
        stats=stats,
        now=datetime.utcnow()
    )


# ============ EMPLOYEE DASHBOARD ============
@app.route('/employee/dashboard')
@login_required
def employee_dashboard():
    if current_user.role != 'employee':
        flash('Access denied. Employee privileges required.', 'error')
        return redirect(url_for('dashboard'))
    
    check_deadline_notifications()
    tasks = Task.query.filter_by(employee_id=current_user.id).order_by(Task.deadline.asc()).all()
    stats = current_user.get_stats()
    
    return render_template(
        "employee_dashboard.html",
        tasks=tasks,
        stats=stats,
        now=datetime.utcnow()
    )


# ============ ✅ ADMIN TASK CREATION - WITH FIXED URL GENERATION ============
@app.route('/admin/create_task', methods=['GET', 'POST'])
@login_required
def create_task():
    if current_user.role != 'admin':
        flash('Unauthorized access.', 'error')
        return redirect(url_for('dashboard'))
    
    employees = User.query.filter_by(role='employee', is_active=True).all()
    
    if request.method == 'POST':
        try:
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            employee_id = request.form.get('employee_id')
            deadline_str = request.form.get('deadline')
            priority = request.form.get('priority', 'medium')
            
            if not all([title, employee_id, deadline_str]):
                flash('All required fields must be filled.', 'error')
                return render_template('create_task.html', employees=employees)
            
            deadline = datetime.strptime(deadline_str, '%Y-%m-%dT%H:%M')
            task_id = generate_task_id()
            
            # ✅ STEP 1: Save attachment file FIRST
            admin_attachment = None
            admin_attachment_name = None
            preview_url = None
            download_url = None
            
            if 'admin_attachment' in request.files:
                file = request.files['admin_attachment']
                if file and file.filename:
                    filename = secure_filename(f"{task_id}_{file.filename}")
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'admin_files', filename)
                    file.save(filepath)
                    admin_attachment = f'admin_files/{filename}'
                    admin_attachment_name = filename
                    # ✅ FIXED: Added "/" separator in URL construction
                    base_url = request.url_root.rstrip('/')
                    preview_url = f"{base_url}/download/{admin_attachment}"
                    download_url = f"{base_url}/download/{admin_attachment}?force=1"
            
            # ✅ STEP 2: Create and save task
            task = Task(
                task_id=task_id,
                title=title,
                description=description,
                deadline=deadline,
                status='pending',
                priority=priority,
                employee_id=int(employee_id),
                created_by=current_user.id,
                admin_attachment=admin_attachment
            )
            db.session.add(task)
            db.session.commit()
            
            # ✅ STEP 3: Generate WhatsApp message WITH PREVIEW + DOWNLOAD
            employee = User.query.get(int(employee_id))
            if employee and employee.phone:
                whatsapp_msg = "📋 *NEW TASK ASSIGNED* 📋\n\n"
                whatsapp_msg += f"🔖 *Task ID:* {task.task_id}\n"
                whatsapp_msg += f"📌 *Title:* {task.title}\n"
                whatsapp_msg += f"📝 *Description:* {description[:150]}{'...' if len(description) > 150 else ''}\n"
                whatsapp_msg += f"⏰ *Deadline:* {deadline.strftime('%b %d, %Y at %I:%M %p')}\n"
                whatsapp_msg += f"🔥 *Priority:* {priority.upper()}\n"
                whatsapp_msg += f"👤 *Assigned By:* {current_user.name}\n"
                
                if admin_attachment_name:
                    whatsapp_msg += f"\n📎 *Attachment:* {admin_attachment_name}\n"
                    whatsapp_msg += f"👁️ *Preview:* {preview_url}\n"
                    whatsapp_msg += f"📥 *Download:* {download_url}\n"
                
                whatsapp_msg += f"\n✅ *Check dashboard for full details:*\n"
                whatsapp_msg += f"{request.url_root.rstrip('/')}/employee/task/{task.id}"
                
                task.whatsapp_notify_link = generate_whatsapp_link(employee.phone, whatsapp_msg)
                db.session.commit()
            
            send_notification(
                int(employee_id),
                f"📋 New Task Assigned: '{title}' (ID: {task_id})",
                task.id,
                'info'
            )
            
            flash(f'Task {task_id} created successfully! ✅', 'success')
            return redirect(url_for('admin_task_detail', task_id=task.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating task: {str(e)}', 'error')
            return render_template('create_task.html', employees=employees)
    
    return render_template('create_task.html', employees=employees)


# ============ TASK DETAIL & MANAGEMENT ============
@app.route('/admin/task/<int:task_id>')
@login_required
def admin_task_detail(task_id):
    if current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    
    task = db.session.get(Task, task_id)
    if not task:
        flash('Task not found.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    documents = TaskDocument.query.filter_by(task_id=task_id).all()
    return render_template('task_detail.html', task=task, documents=documents, user_role='admin', now=datetime.utcnow())


@app.route('/employee/task/<int:task_id>')
@login_required
def employee_task_detail(task_id):
    task = db.session.get(Task, task_id)
    if not task:
        flash('Task not found.', 'error')
        return redirect(url_for('employee_dashboard'))
    
    if task.employee_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    
    documents = TaskDocument.query.filter_by(task_id=task_id).all()
    return render_template('task_detail.html', task=task, documents=documents, user_role='employee', now=datetime.utcnow())


# ============ ✅ EMPLOYEE SUBMISSION - WITH FIXED URL GENERATION ============
@app.route('/employee/submit_task/<int:task_id>', methods=['POST'])
@login_required
def submit_task(task_id):
    task = db.session.get(Task, task_id)
    if not task or task.employee_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    if task.status in ['submitted', 'verified']:
        return jsonify({'success': False, 'error': 'Already submitted'}), 400
    
    try:
        employee_attachment = None
        employee_attachment_name = None
        preview_url = None
        download_url = None
        
        if 'employee_attachment' in request.files:
            file = request.files['employee_attachment']
            if file and file.filename:
                filename = secure_filename(f"{task.task_id}_sub_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'employee_files', filename)
                file.save(filepath)
                employee_attachment = f'employee_files/{filename}'
                employee_attachment_name = filename
                # ✅ FIXED: Added "/" separator in URL construction
                base_url = request.url_root.rstrip('/')
                preview_url = f"{base_url}/download/{employee_attachment}"
                download_url = f"{base_url}/download/{employee_attachment}?force=1"
                
                doc = TaskDocument(
                    task_id=task.id,
                    uploaded_by=current_user.id,
                    filename=filename,
                    original_filename=file.filename,
                    file_type=file.content_type,
                    file_size=os.path.getsize(filepath)
                )
                db.session.add(doc)
        
        task.status = 'submitted'
        task.completed_at = datetime.utcnow()
        task.employee_attachment = employee_attachment
        db.session.commit()
        
        if task.creator and task.creator.phone:
            whatsapp_msg = "✅ *TASK SUBMITTED* ✅\n\n"
            whatsapp_msg += f"🔖 *Task ID:* {task.task_id}\n"
            whatsapp_msg += f"📌 *Title:* {task.title}\n"
            whatsapp_msg += f"👤 *Submitted By:* {current_user.name}\n"
            whatsapp_msg += f"⏰ *Submitted At:* {datetime.utcnow().strftime('%b %d, %Y %I:%M %p')}\n"
            
            if employee_attachment_name:
                whatsapp_msg += f"\n📎 *Work File:* {employee_attachment_name}\n"
                whatsapp_msg += f"👁️ *Preview:* {preview_url}\n"
                whatsapp_msg += f"📥 *Download:* {download_url}\n"
            
            docs = TaskDocument.query.filter_by(task_id=task.id).all()
            if docs:
                whatsapp_msg += f"📁 *Total Files:* {len(docs)}\n"
            
            whatsapp_msg += f"\n🔍 *Verify in dashboard:*\n"
            whatsapp_msg += f"{request.url_root.rstrip('/')}/admin/task/{task.id}"
            
            task.whatsapp_submission_link = generate_whatsapp_link(task.creator.phone, whatsapp_msg)
            db.session.commit()
        
        send_notification(task.created_by, f"✅ Task Submitted: '{task.title}'", task.id, 'success')
        return jsonify({'success': True, 'message': 'Task submitted successfully!'})
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Submit task error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ ✅ ADMIN VERIFICATION - WITH FIXED URL GENERATION ============
@app.route('/admin/verify_task/<int:task_id>', methods=['POST'])
@login_required
def verify_task(task_id):
    if current_user.role != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    
    try:
        action = request.form.get('action')
        notes = request.form.get('verification_notes', '').strip()
        base_url = request.url_root.rstrip('/')
        
        if action == 'approve':
            task.status = 'verified'
            task.verified_at = datetime.utcnow()
            task.verified_by = current_user.id
            task.verification_notes = notes
            
            send_notification(task.employee_id, f"🎉 Task Verified: '{task.title}'", task.id, 'success')
            
            if task.employee and task.employee.phone:
                whatsapp_msg = "🎉 *TASK APPROVED* 🎉\n\n"
                whatsapp_msg += f"🔖 *Task ID:* {task.task_id}\n"
                whatsapp_msg += f"📌 *Title:* {task.title}\n"
                whatsapp_msg += f"✅ *Status:* COMPLETED\n"
                whatsapp_msg += f"📝 *Notes:* {notes[:150] if notes else 'Well done!'}\n"
                whatsapp_msg += f"🕐 *Verified At:* {datetime.utcnow().strftime('%b %d, %Y %I:%M %p')}\n"
                
                if task.employee_attachment:
                    attachment_name = task.employee_attachment.split('/')[-1]
                    preview_url = f"{base_url}/download/{task.employee_attachment}"
                    download_url = f"{base_url}/download/{task.employee_attachment}?force=1"
                    whatsapp_msg += f"\n📎 *Your File:* {attachment_name}\n"
                    whatsapp_msg += f"👁️ *Preview:* {preview_url}\n"
                    whatsapp_msg += f"📥 *Download:* {download_url}\n"
                
                docs = TaskDocument.query.filter_by(task_id=task.id).all()
                if docs:
                    whatsapp_msg += f"📁 *Total Files:* {len(docs)}\n"
                
                whatsapp_msg += f"\n✨ Great work! Check dashboard for completion certificate."
                
                task.whatsapp_verification_link = generate_whatsapp_link(task.employee.phone, whatsapp_msg)
                db.session.commit()
            
            msg = 'Task approved!'
            
        elif action == 'reject':
            task.status = 'pending'
            task.verification_notes = f"Rejected: {notes}"
            
            send_notification(task.employee_id, f"⚠️ Task Returned: '{task.title}'", task.id, 'warning')
            
            if task.employee and task.employee.phone:
                whatsapp_msg = "⚠️ *TASK RETURNED FOR REVISION* ⚠️\n\n"
                whatsapp_msg += f"🔖 *Task ID:* {task.task_id}\n"
                whatsapp_msg += f"📌 *Title:* {task.title}\n"
                whatsapp_msg += f"❌ *Status:* Needs Revision\n"
                whatsapp_msg += f"📝 *Feedback:* {notes[:200] if notes else 'Please review and resubmit'}\n"
                whatsapp_msg += f"🕐 *Returned At:* {datetime.utcnow().strftime('%b %d, %Y %I:%M %p')}\n"
                
                if task.employee_attachment:
                    attachment_name = task.employee_attachment.split('/')[-1]
                    preview_url = f"{base_url}/download/{task.employee_attachment}"
                    download_url = f"{base_url}/download/{task.employee_attachment}?force=1"
                    whatsapp_msg += f"\n📎 *Submitted File:* {attachment_name}\n"
                    whatsapp_msg += f"👁️ *Preview:* {preview_url}\n"
                    whatsapp_msg += f"📥 *Download:* {download_url}\n"
                
                whatsapp_msg += f"\n🔄 Please update and resubmit via dashboard."
                
                task.whatsapp_verification_link = generate_whatsapp_link(task.employee.phone, whatsapp_msg)
                db.session.commit()
            
            msg = 'Task returned for revision.'
        
        else:
            flash('Invalid action.', 'error')
            return redirect(url_for('admin_task_detail', task_id=task_id))
        
        db.session.commit()
        flash(msg, 'success')
        return redirect(url_for('admin_task_detail', task_id=task_id))
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Verify task error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ ADMIN: DELETE EMPLOYEE ============
@app.route('/admin/delete_employee/<int:user_id>')
@login_required
def delete_employee(user_id):
    if current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    user = db.session.get(User, user_id)
    if user and user.role == 'employee':
        pending = Task.query.filter_by(employee_id=user_id, status='pending').count()
        if pending > 0:
            flash(f'❌ Cannot delete. User has {pending} pending task(s).', 'error')
        else:
            user.is_active = False
            db.session.commit()
            flash(f'🗑️ Employee "{user.name}" deactivated successfully.', 'success')
    else:
        flash('❌ Invalid user or cannot delete admins.', 'error')
    
    return redirect(url_for('admin_dashboard'))


# ============ REPORTS & ANALYTICS ============
@app.route('/admin/reports')
@login_required
def reports():
    if current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    
    tasks = Task.query.all()
    employees = User.query.filter_by(role='employee').all()
    stats = get_task_stats()
    chart_data = get_chart_data()
    
    filter_emp = request.args.get('employee')
    filter_status = request.args.get('status')
    filter_date = request.args.get('date_range')
    
    if filter_emp and filter_emp.isdigit():
        tasks = [t for t in tasks if t.employee_id == int(filter_emp)]
    if filter_status:
        tasks = [t for t in tasks if t.status == filter_status]
    if filter_date:
        if filter_date == 'overdue':
            tasks = [t for t in tasks if t.deadline and t.deadline < datetime.utcnow() and t.status != 'verified']
        elif filter_date == 'today':
            today = datetime.utcnow().date()
            tasks = [t for t in tasks if t.created_at.date() == today]
    
    return render_template(
        'reports.html',
        tasks=tasks,
        stats=stats,
        chart_data=chart_data,
        employees=employees,
        filters={'employee': filter_emp, 'status': filter_status, 'date_range': filter_date},
        now=datetime.utcnow()
    )


# ============ EXPORT FUNCTIONS ============
@app.route('/admin/export_excel')
@login_required
def export_excel():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        tasks = Task.query.all()
        data = []
        for task in tasks:
            data.append({
                'Task ID': task.task_id,
                'Title': task.title,
                'Employee': task.employee.name if task.employee else 'N/A',
                'Designation': task.employee.designation if task.employee else 'N/A',
                'Status': task.status,
                'Priority': task.priority,
                'Deadline': task.deadline.strftime('%Y-%m-%d %H:%M') if task.deadline else '',
                'Completed': task.completed_at.strftime('%Y-%m-%d %H:%M') if task.completed_at else '',
                'Verified': task.verified_at.strftime('%Y-%m-%d %H:%M') if task.verified_at else '',
                'Created': task.created_at.strftime('%Y-%m-%d')
            })
        
        df = pd.DataFrame(data)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Tasks')
        output.seek(0)
        
        filename = f'SLCI_Report_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        return response
        
    except Exception as e:
        app.logger.error(f'Export error: {str(e)}')
        return jsonify({'error': str(e)}), 500


# ============ NOTIFICATIONS API ============
@app.route('/api/notifications')
@login_required
def get_notifications():
    notifications = Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).order_by(Notification.created_at.desc()).limit(10).all()
    return jsonify([n.to_dict() for n in notifications])


@app.route('/api/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notif_id):
    notification = db.session.get(Notification, notif_id)
    if notification and notification.user_id == current_user.id:
        notification.is_read = True
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False}), 404


# ============ ✅ FILE DOWNLOAD ROUTE - FULLY FIXED ============
@app.route('/download/<path:filename>')
@login_required
def download_file(filename):
    """
    Serves file for download or preview.
    - If ?force=1 in URL: Forces download (as_attachment=True)
    - Otherwise: Opens in browser for preview (as_attachment=False)
    """
    # Security: Validate filename
    safe_filename = secure_filename(filename)
    if not safe_filename:
        abort(404)
    
    # Build full path
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    # Security: Prevent path traversal
    if not os.path.abspath(full_path).startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
        abort(403)
    
    if not os.path.exists(full_path):
        abort(404)
    
    force_download = request.args.get('force', '0') == '1'
    
    # Get just the filename for download_name
    download_name = os.path.basename(filename)
    
    return send_from_directory(
        app.config['UPLOAD_FOLDER'], 
        filename, 
        as_attachment=force_download,
        download_name=download_name
    )


# ============ VOICE PROCESSING API ============
@app.route('/api/process_voice', methods=['POST'])
@login_required
def api_process_voice():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    if 'voice' not in request.files:
        return jsonify({'success': False, 'error': 'No audio file'}), 400
    
    voice = request.files['voice']
    if voice.filename == '':
        return jsonify({'success': False, 'error': 'Empty filename'}), 400
    
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = secure_filename(f"{timestamp}_voice.webm")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        voice.save(filepath)
        
        employee_list = [
            {'id': u.id, 'name': u.name.lower()}
            for u in User.query.filter_by(role='employee').all()
        ]
        
        task_data = process_voice_task(filepath, employee_list=employee_list)
        return jsonify({'success': True, 'task': task_data})
        
    except Exception as e:
        app.logger.error(f'Voice processing error: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass


@app.route('/api/create_task', methods=['POST'])
@login_required
def api_create_task():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    data = request.get_json()
    if not data or 'task' not in data:
        return jsonify({'success': False, 'error': 'Invalid payload'}), 400
    
    task_info = data['task']
    try:
        task_id = generate_task_id()
        deadline = datetime.fromisoformat(task_info['deadline']) if task_info.get('deadline') else datetime.now() + timedelta(days=2)
        
        task = Task(
            task_id=task_id,
            title=task_info['title'][:200],
            description=task_info.get('description', '')[:2000],
            deadline=deadline,
            status='pending',
            employee_id=task_info.get('employee_id') or current_user.id,
            created_by=current_user.id,
            priority=task_info.get('priority', 'medium')
        )
        db.session.add(task)
        db.session.commit()
        
        return jsonify({'success': True, 'task_id': task.id, 'task_code': task_id})
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'API task creation error: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ GLOBAL HOOKS ============
@app.before_request
def before_request():
    if current_user.is_authenticated:
        check_deadline_notifications()


@app.context_processor
def inject_globals():
    return {
        'current_year': datetime.now().year,
        'app_name': 'SLCI Delegation Dashboard',
        'generate_whatsapp_link': generate_whatsapp_link,
        'now': datetime.utcnow()
    }


# ============ ERROR HANDLERS ============
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500


# ============ MAIN ENTRY POINT ============
if __name__ == "__main__":
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    host = '0.0.0.0' if os.getenv('FLASK_ENV') == 'production' else '127.0.0.1'
    port = int(os.getenv('PORT', 5000))
    print(f"🚀 Starting SLCI Dashboard on http://{host}:{port}")
    print(f"📊 Features: Admin Panel • Employee Tasks • Reports • Charts • Export • Voice • Dark Mode")
    print(f"💬 WhatsApp: Full details + 👁️ Preview + 📥 Download links ✅")
    app.run(host=host, port=port, debug=debug)