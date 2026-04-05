from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(80), nullable=False)
    method = db.Column(db.String(10), nullable=False)
    path = db.Column(db.String(255), nullable=False)
    salesorder_id = db.Column(db.String(100), nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Customer(db.Model):
    __tablename__ = 'customers'
    customer_id = db.Column(db.String(100), primary_key=True)
    customer_name = db.Column(db.String(200))
    email = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(500), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    zip = db.Column(db.String(50), nullable=True)


class Item(db.Model):
    __tablename__ = 'items'
    item_id = db.Column(db.String(100), primary_key=True)
    item_name = db.Column(db.String(200))
    description = db.Column(db.String(500), nullable=True)


class Employee(db.Model):
    __tablename__ = 'employees'

    employee_id = db.Column(db.String(50), primary_key=True)
    employee_name = db.Column(db.String(200))
    email = db.Column(db.String(200))
    office = db.Column(db.String(100))
    position = db.Column(db.String(100))
    salesperson_id = db.Column(db.String(50))


class TaskTemplate(db.Model):
    __tablename__ = 'task_templates'

    id = db.Column(db.Integer, primary_key=True)
    country = db.Column(db.String(100))
    order = db.Column(db.Integer)
    title = db.Column(db.String(200))
    description = db.Column(db.String(500))
    books_field = db.Column(db.String(100))


class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    books_sales_order_id = db.Column(db.String(50))
    template_id = db.Column(db.Integer, db.ForeignKey('task_templates.id'))
    assigned_to = db.Column(db.String(50), db.ForeignKey('employees.employee_id'))
    status = db.Column(db.String(20), default='pending')
    completed_value = db.Column(db.String(500))
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    template = db.relationship('TaskTemplate', backref='tasks')
    employee = db.relationship('Employee', backref='tasks')

class ContractMeta(db.Model):
    __tablename__ = 'contract_meta'
    id = db.Column(db.Integer, primary_key=True)
    books_sales_order_id = db.Column(db.String(100), unique=True, nullable=False)
    in_network = db.Column(db.Boolean, nullable=True)


class Shipment(db.Model):
    __tablename__ = 'shipments'
    id = db.Column(db.Integer, primary_key=True)
    books_sales_order_id = db.Column(db.String(100), nullable=False)
    vessel_name = db.Column(db.String(200), nullable=True)
    booking_number = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
