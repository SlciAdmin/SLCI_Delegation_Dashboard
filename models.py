#!/usr/bin/env python3
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    def set_password(self, password):
        self.password = generate_password_hash(password, method='pbkdf2:sha256')
    
    def check_password(self, password):
        return check_password_hash(self.password, password)
    
    def get_stats(self):
        tasks = self.assigned_tasks.all()
        return {
            'total': len(tasks),
            'pending': len([t for t in tasks if t.status == 'pending']),
            'in_progress': len([t for t in tasks if t.status == 'in_progress']),
            'submitted': len([t for t in tasks if t.status == 'submitted']),
            'verified': len([t for t in tasks if t.status == 'verified']),
            'overdue': len([t for t in tasks if t.deadline and t.deadline < datetime.utcnow() and t.status != 'verified'])
        }

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