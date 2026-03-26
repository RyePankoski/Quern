from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Customer(db.Model):
    __tablename__ = 'customers'

    customer_id = db.Column(db.String(50), primary_key=True)
    customer_name = db.Column(db.String(200))

class Item(db.Model):
    __tablename__ = 'items'

    item_id = db.Column(db.String(50), primary_key=True)
    item_name = db.Column(db.String(200))

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

