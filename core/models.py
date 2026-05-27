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
    email = db.Column(db.String(200), unique=True, nullable=False)
    display_name = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(50), nullable=False, default='broker')

    @property
    def is_admin(self):
        return self.role == 'admin'


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
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Item(db.Model):
    __tablename__ = 'items'
    item_id = db.Column(db.String(100), primary_key=True)
    item_name = db.Column(db.String(200))
    description = db.Column(db.String(500), nullable=True)
    origin = db.Column(db.String(200), nullable=True)
    pnl_group = db.Column(db.String(200), nullable=True)
    pnl_group_tag_option_id = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Employee(db.Model):
    __tablename__ = 'employees'

    employee_id = db.Column(db.String(50), primary_key=True)
    employee_name = db.Column(db.String(200))
    email = db.Column(db.String(200))
    office = db.Column(db.String(100))
    position = db.Column(db.String(100))
    salesperson_id = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, nullable=False, default=True)


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


class Contract(db.Model):
    __tablename__ = 'contracts'

    # Zoho identifiers
    salesorder_id            = db.Column(db.String(100), primary_key=True)
    salesorder_number        = db.Column(db.String(100))
    status                   = db.Column(db.String(50))
    last_modified_time       = db.Column(db.String(50))

    # Dates
    date                     = db.Column(db.String(20))
    shipment_date            = db.Column(db.String(20))
    cf_shipment_end_date     = db.Column(db.String(20))

    # Seller
    customer_id              = db.Column(db.String(100))
    customer_name            = db.Column(db.String(200))

    # Buyer
    cf_buyer                 = db.Column(db.String(200))
    cf_buyer_id              = db.Column(db.String(100))

    # Line item
    item_id                  = db.Column(db.String(100))
    item_name                = db.Column(db.String(200))
    quantity                 = db.Column(db.Float)
    rate                     = db.Column(db.Float)

    # Custom fields
    cf_item_contract_price   = db.Column(db.Float)
    cf_trnspname             = db.Column(db.String(100))
    cf_uom                   = db.Column(db.String(100))
    cf_customer_ref          = db.Column(db.String(200))
    cf_co_broker             = db.Column(db.String(200))
    cf_co_brokerage_rate     = db.Column(db.Float)
    cf_split_broker          = db.Column(db.String(200))
    cf_split_percentage      = db.Column(db.Float)
    cf_vessel_name           = db.Column(db.String(200))
    cf_origin_location       = db.Column(db.String(200))

    # Zoho top-level
    salesperson_name         = db.Column(db.String(200))
    salesperson_id           = db.Column(db.String(100))
    location_id              = db.Column(db.String(100))
    location_name            = db.Column(db.String(200))
    reference_number         = db.Column(db.String(500))
    notes                    = db.Column(db.Text)
    terms                    = db.Column(db.Text)

    # Quern-local
    in_network               = db.Column(db.Boolean)
    buyer_reference          = db.Column(db.String(200))
    packing                  = db.Column(db.String(20))
    packing                  = db.Column(db.String(20))


class Shipment(db.Model):
    __tablename__ = 'shipments'
    id = db.Column(db.Integer, primary_key=True)
    books_sales_order_id = db.Column(db.String(100), nullable=False)
    vessel_name = db.Column(db.String(200), nullable=True)
    booking_number = db.Column(db.String(200), nullable=True)
    quantity = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ContractNote(db.Model):
    __tablename__ = 'contract_notes'
    id = db.Column(db.Integer, primary_key=True)
    books_sales_order_id = db.Column(db.String(100), nullable=False)
    author = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BrokerCommission(db.Model):
    __tablename__ = 'broker_commissions'
    id = db.Column(db.Integer, primary_key=True)
    books_sales_order_id = db.Column(db.String(100), nullable=False)
    employee_id = db.Column(db.String(100), nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SyncState(db.Model):
    __tablename__ = 'sync_state'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(200), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)