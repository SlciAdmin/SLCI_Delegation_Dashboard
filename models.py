#!/usr/bin/env python3
"""
SLCI Delegation Dashboard - Database Models
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='employee')
    designation = db.Column(db.String(100), default='Employee')
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    assigned_tasks = db.relationship('Task', backref='employee', lazy='dynamic',
                                    foreign_keys='Task.employee_id')
    created_tasks = db.relationship('Task', backref='creator', lazy='dynamic',
                                   foreign_keys='Task.created_by')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic',
                                   cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password = generate_password_hash(password, method='pbkdf2:sha256')
    
    def check_password(self, password):
        return check_password_hash(self.password, password)
    
    def get_stats(self):
        """Get task statistics for this user"""
        tasks = self.assigned_tasks.all()
        return {
            'total': len(tasks),
            'pending': len([t for t in tasks if t.status == 'pending']),
            'in_progress': len([t for t in tasks if t.status == 'in_progress']),
            'submitted': len([t for t in tasks if t.status == 'submitted']),
            'verified': len([t for t in tasks if t.status == 'verified']),
            'overdue': len([t for t in tasks if t.deadline and t.deadline < datetime.utcnow() and t.status != 'verified'])
        }
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'role': self.role,
            'designation': self.designation,
            'phone': self.phone
        }
    
    def __repr__(self):
        return f'<User {self.email}>'


class Task(db.Model):
    __tablename__ = 'tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    deadline = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(50), default="pending")
    priority = db.Column(db.String(20), default="medium")
    employee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    verification_notes = db.Column(db.Text)
    
    # Files
    admin_attachment = db.Column(db.String(500))
    employee_attachment = db.Column(db.String(500))
    
    # Notifications Flags
    notification_3hr_sent = db.Column(db.Boolean, default=False)
    notification_1hr_sent = db.Column(db.Boolean, default=False)
    whatsapp_notify_link = db.Column(db.String(1000))  # Task assignment
    whatsapp_submission_link = db.Column(db.String(1000))  # Employee submission
    whatsapp_verification_link = db.Column(db.String(1000))  # Admin verification
    whatsapp_reminder_3hr = db.Column(db.String(1000))  # 3-hour deadline reminder
    whatsapp_reminder_1hr = db.Column(db.String(1000))  # 1-hour deadline reminder
    
    def is_overdue(self):
        return self.deadline and self.deadline < datetime.utcnow() and self.status != 'verified'
    
    def to_dict(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'title': self.title,
            'description': self.description,
            'deadline': self.deadline.isoformat() if self.deadline else None,
            'status': self.status,
            'priority': self.priority,
            'employee_id': self.employee_id,
            'employee_name': self.employee.name if self.employee else None,
            'created_by': self.created_by,
            'creator_name': self.creator.name if self.creator else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None
        }
    
    def __repr__(self):
        return f'<Task {self.task_id}>'


class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=True)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), default='info')
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
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
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50))
    file_size = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    task = db.relationship('Task', backref='documents')
    uploader = db.relationship('User', backref='uploaded_documents')
    
    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'file_type': self.file_type,
            'file_size': self.file_size,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'uploaded_by': self.uploader.name if self.uploader else None
        }