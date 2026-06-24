"""
test_quern.py — Quern test suite
Run with: pytest test_quern.py -v

Covers:
  - Model properties (Contract.total, User.is_admin)
  - upsert_contract_from_zoho (field mapping, update vs insert, safe_float, cf_buyer_id resolution)
  - contract_to_form_data_local
  - check_task_reactivity
  - generate_tasks
  - Route auth (unauthenticated → redirect, admin-only → 403-redirect for brokers)
  - Route logic (toggle_decline, add_shipment, delete_shipment, 404 handling)
  - Admin user management (create, role update, delete, self-delete prevention)

External services (Zoho API, MSAL) are fully mocked — no network calls.
"""

import os
import pytest
from datetime import datetime

# ---------------------------------------------------------------------------
# Minimal Flask app fixture (mirrors app.py structure without real imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ZOHO_CLIENT_ID", "fake")
os.environ.setdefault("ZOHO_CLIENT_SECRET", "fake")
os.environ.setdefault("ZOHO_REFRESH_TOKEN", "fake")
os.environ.setdefault("ZOHO_ORG_ID", "fake")

# We import models directly since the project files are available at their
# real paths. Adjust sys.path so the flat project layout is importable.
import sys
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user
from flask_migrate import Migrate
from sqlalchemy.orm import DeclarativeBase


# ---------------------------------------------------------------------------
# Re-create the minimal model layer from models.py for isolated testing.
# (Avoids importing app.py which has side effects and Zoho calls at module
#  level via `from functions import *`.)
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    display_name = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(50), nullable=False, default="broker")

    @property
    def is_admin(self):
        return self.role == "admin"


class Customer(db.Model):
    __tablename__ = "customers"
    customer_id = db.Column(db.String(100), primary_key=True)
    customer_name = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Item(db.Model):
    __tablename__ = "items"
    item_id = db.Column(db.String(100), primary_key=True)
    item_name = db.Column(db.String(200))
    origin = db.Column(db.String(200), nullable=True)
    pnl_group = db.Column(db.String(200), nullable=True)
    pnl_group_tag_option_id = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Employee(db.Model):
    __tablename__ = "employees"
    employee_id = db.Column(db.String(50), primary_key=True)
    employee_name = db.Column(db.String(200))
    email = db.Column(db.String(200))
    office = db.Column(db.String(100))
    position = db.Column(db.String(100))
    salesperson_id = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class TaskTemplate(db.Model):
    __tablename__ = "task_templates"
    id = db.Column(db.Integer, primary_key=True)
    country = db.Column(db.String(100))
    order = db.Column(db.Integer)
    title = db.Column(db.String(200))
    description = db.Column(db.String(500))
    books_field = db.Column(db.String(100))


class Task(db.Model):
    __tablename__ = "tasks"
    id = db.Column(db.Integer, primary_key=True)
    books_sales_order_id = db.Column(db.String(50))
    template_id = db.Column(db.Integer, db.ForeignKey("task_templates.id"))
    assigned_to = db.Column(db.String(50))
    status = db.Column(db.String(20), default="pending")
    completed_value = db.Column(db.String(500))
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    template = db.relationship("TaskTemplate", backref="tasks")


class Contract(db.Model):
    __tablename__ = "contracts"
    salesorder_id = db.Column(db.String(100), primary_key=True)
    salesorder_number = db.Column(db.String(100))
    status = db.Column(db.String(50))
    last_modified_time = db.Column(db.String(50))
    date = db.Column(db.String(20))
    shipment_date = db.Column(db.String(20))
    cf_shipment_end_date = db.Column(db.String(20))
    customer_id = db.Column(db.String(100))
    customer_name = db.Column(db.String(200))
    cf_buyer = db.Column(db.String(200))
    cf_buyer_id = db.Column(db.String(100))
    item_id = db.Column(db.String(100))
    item_name = db.Column(db.String(200))
    quantity = db.Column(db.Float)
    rate = db.Column(db.Float)
    cf_item_contract_price = db.Column(db.String(100))
    cf_trnspname = db.Column(db.String(100))
    cf_uom = db.Column(db.String(100))
    cf_customer_ref = db.Column(db.String(200))
    cf_co_broker = db.Column(db.String(200))
    cf_co_brokerage_rate = db.Column(db.Float)
    cf_split_broker = db.Column(db.String(200))
    cf_split_percentage = db.Column(db.Float)
    cf_vessel_name = db.Column(db.String(200))
    cf_origin_location = db.Column(db.String(200))
    salesperson_name = db.Column(db.String(200))
    salesperson_id = db.Column(db.String(100))
    location_id = db.Column(db.String(100))
    location_name = db.Column(db.String(200))
    reference_number = db.Column(db.String(500))
    notes = db.Column(db.Text)
    terms = db.Column(db.Text)
    in_network = db.Column(db.Boolean)
    buyer_reference = db.Column(db.String(200))
    is_declined = db.Column(db.Boolean, default=False)
    packing = db.Column(db.String(20))

    @property
    def total(self):
        return (self.rate or 0) * (self.quantity or 0)


class Shipment(db.Model):
    __tablename__ = "shipments"
    id = db.Column(db.Integer, primary_key=True)
    books_sales_order_id = db.Column(db.String(100), nullable=False)
    vessel_name = db.Column(db.String(200), nullable=True)
    booking_number = db.Column(db.String(200), nullable=True)
    quantity = db.Column(db.Float, nullable=True)


class ContractNote(db.Model):
    __tablename__ = "contract_notes"
    id = db.Column(db.Integer, primary_key=True)
    books_sales_order_id = db.Column(db.String(100), nullable=False)
    author = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(80), nullable=False)
    method = db.Column(db.String(10), nullable=False)
    path = db.Column(db.String(255), nullable=False)
    salesorder_id = db.Column(db.String(100), nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False)


class BrokerCommission(db.Model):
    __tablename__ = "broker_commissions"
    id = db.Column(db.Integer, primary_key=True)
    books_sales_order_id = db.Column(db.String(100), nullable=False)
    employee_id = db.Column(db.String(100), nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)


class SyncState(db.Model):
    __tablename__ = "sync_state"
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(200), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Inline ports of the pure-logic functions under test
# (These are copied from zoho.py / tasks.py with the db/model references
#  swapped to point at the models defined above.)
# ---------------------------------------------------------------------------

def _safe_float(val):
    try:
        return float(val) if val not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


def upsert_contract_from_zoho(detail):
    salesorder_id = detail.get("salesorder_id", "")
    if not salesorder_id:
        return

    custom = {f["api_name"]: f["value"] for f in detail.get("custom_fields", [])}
    line_items = detail.get("line_items", [])
    first_item = line_items[0] if line_items else {}

    existing = Contract.query.get(salesorder_id)
    if not existing:
        existing = Contract(salesorder_id=salesorder_id)
        db.session.add(existing)

    existing.salesorder_number = detail.get("salesorder_number", "")
    existing.status = detail.get("status", "")
    existing.last_modified_time = detail.get("last_modified_time", "")
    existing.date = detail.get("date", "")
    existing.shipment_date = detail.get("shipment_date", "")
    existing.cf_shipment_end_date = custom.get("cf_shipment_end_date", "")
    existing.customer_id = detail.get("customer_id", "")
    existing.customer_name = detail.get("customer_name", "")
    existing.cf_buyer = custom.get("cf_buyer", "")
    buyer_name = custom.get("cf_buyer", "")
    buyer_customer = Customer.query.filter_by(customer_name=buyer_name).first() if buyer_name else None
    existing.cf_buyer_id = buyer_customer.customer_id if buyer_customer else None
    existing.item_id = first_item.get("item_id", "")
    existing.item_name = first_item.get("name", "")
    existing.quantity = first_item.get("quantity")
    existing.rate = first_item.get("rate")
    existing.cf_item_contract_price = custom.get("cf_item_contract_price", "")
    existing.cf_trnspname = custom.get("cf_trnspname", "")
    existing.cf_uom = custom.get("cf_uom", "")
    existing.cf_customer_ref = custom.get("cf_customer_ref", "")
    existing.cf_co_broker = custom.get("cf_co_broker", "")
    existing.cf_co_brokerage_rate = _safe_float(custom.get("cf_co_brokerage_rate"))
    existing.cf_split_broker = custom.get("cf_split_broker", "")
    existing.cf_split_percentage = _safe_float(custom.get("cf_split_percentage"))
    existing.cf_vessel_name = custom.get("cf_vessel_name", "")
    existing.cf_origin_location = custom.get("cf_origin_location", "")
    existing.salesperson_name = detail.get("salesperson_name", "")
    existing.salesperson_id = detail.get("salesperson_id", "")
    existing.location_id = detail.get("location_id", "")
    existing.location_name = detail.get("location_name", "")
    existing.reference_number = detail.get("reference_number", "")
    existing.notes = detail.get("notes", "")
    existing.terms = detail.get("terms", "")
    db.session.commit()


def contract_to_form_data_local(contract):
    buyer_id = contract.cf_buyer_id
    if not buyer_id and contract.cf_buyer:
        buyer_customer = Customer.query.filter_by(customer_name=contract.cf_buyer).first()
        buyer_id = buyer_customer.customer_id if buyer_customer else ""
    return {
        "seller": contract.customer_id or "",
        "buyer": buyer_id or "",
        "contract_date": "",
        "shipping_date": "",
        "shipping_date_end": contract.shipment_date or contract.cf_shipment_end_date or "",
        "delivery_notes": contract.notes or "",
        "terms": contract.terms or "",
        "commodity": contract.item_id or "",
        "commission_rate": contract.rate or "",
        "quantity": contract.quantity or "",
        "commodity_rate": contract.cf_item_contract_price or "",
        "transportation": contract.cf_trnspname or "",
        "uom": contract.cf_uom or "",
        "seller_reference": contract.cf_customer_ref or "",
        "co_broker_name": contract.cf_co_broker or "",
        "co_brokerage_rate": contract.cf_co_brokerage_rate or "",
        "location_id": contract.location_id or "",
        "location_name": contract.location_name or "",
    }


def check_task_reactivity(salesorder_id, changed_fields):
    tasks = Task.query.filter_by(books_sales_order_id=salesorder_id).all()
    for task in tasks:
        if task.status == "complete" and task.template.books_field:
            new_value = changed_fields.get(task.template.books_field)
            if new_value is not None and str(new_value) != str(task.completed_value):
                task.status = "pending"
    db.session.commit()


def generate_tasks(salesorder_id, country="Boulder"):
    existing = Task.query.filter_by(books_sales_order_id=salesorder_id).first()
    if existing:
        return
    templates = TaskTemplate.query.filter_by(country=country).order_by(TaskTemplate.order).all()
    for template in templates:
        task = Task(
            books_sales_order_id=salesorder_id,
            template_id=template.id,
            assigned_to=None,
            status="pending",
        )
        db.session.add(task)
    db.session.commit()


# ---------------------------------------------------------------------------
# App factory and fixtures
# ---------------------------------------------------------------------------

def create_test_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["WTF_CSRF_ENABLED"] = False

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # --- Minimal route set (mirrors app.py) --------------------------------

    from flask_login import login_required, current_user
    from flask import request, redirect, flash, jsonify
    from functools import wraps

    def admin_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.is_admin:
                flash("Admin access required.", "danger")
                return redirect("/")
            return f(*args, **kwargs)
        return decorated

    @app.route("/login_as/<int:user_id>")
    def login_as(user_id):
        user = db.session.get(User, user_id)
        if user:
            login_user(user)
        return redirect("/")

    @app.route("/")
    @login_required
    def home():
        return "home"

    @app.route("/contracts/<salesorder_id>/decline", methods=["POST"])
    @login_required
    def toggle_decline(salesorder_id):
        c = Contract.query.get(salesorder_id)
        if not c:
            return jsonify(ok=False, error="Contract not found"), 404
        c.is_declined = not bool(c.is_declined)
        db.session.commit()
        return jsonify(ok=True, is_declined=c.is_declined)

    @app.route("/contracts/<salesorder_id>/shipments/add", methods=["POST"])
    @login_required
    def add_shipment(salesorder_id):
        data = request.get_json()
        qty_val = data.get("quantity")
        shipment = Shipment(
            books_sales_order_id=salesorder_id,
            booking_number=data.get("booking_number", ""),
            quantity=float(qty_val) if qty_val else None,
        )
        db.session.add(shipment)
        db.session.commit()
        return jsonify(ok=True, id=shipment.id)

    @app.route("/contracts/shipments/<int:shipment_id>/delete", methods=["POST"])
    @login_required
    def delete_shipment(shipment_id):
        shipment = Shipment.query.get(shipment_id)
        if not shipment:
            return jsonify(ok=False), 404
        db.session.delete(shipment)
        db.session.commit()
        return jsonify(ok=True)

    @app.route("/admin/users")
    @login_required
    @admin_required
    def admin_users():
        return "admin users"

    @app.route("/admin/users/create", methods=["POST"])
    @login_required
    @admin_required
    def admin_create_user():
        email = request.form.get("email", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        role = request.form.get("role", "broker")
        if not email:
            flash("Email is required.", "danger")
            return redirect("/admin/users")
        if User.query.filter_by(email=email).first():
            flash(f"{email} already exists.", "warning")
            return redirect("/admin/users")
        db.session.add(User(email=email, display_name=display_name, role=role))
        db.session.commit()
        flash(f"User {email} added.", "success")
        return redirect("/admin/users")

    @app.route("/admin/users/<int:user_id>/role", methods=["POST"])
    @login_required
    @admin_required
    def admin_update_user_role(user_id):
        user = db.session.get(User, user_id)
        if not user:
            flash("User not found.", "danger")
            return redirect("/admin/users")
        new_role = request.form.get("role")
        if new_role not in ("admin", "broker"):
            flash("Invalid role.", "danger")
            return redirect("/admin/users")
        user.role = new_role
        db.session.commit()
        return redirect("/admin/users")

    @app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
    @login_required
    @admin_required
    def admin_delete_user(user_id):
        user = db.session.get(User, user_id)
        if not user:
            flash("User not found.", "danger")
            return redirect("/admin/users")
        if user.id == current_user.id:
            flash("Cannot delete your own account.", "danger")
            return redirect("/admin/users")
        db.session.delete(user)
        db.session.commit()
        flash(f"{user.email} removed.", "success")
        return redirect("/admin/users")

    return app


@pytest.fixture(scope="function")
def app():
    application = create_test_app()
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_user(app):
    u = User(email="admin@test.com", display_name="Admin", role="admin")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def broker_user(app):
    u = User(email="broker@test.com", display_name="Broker", role="broker")
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, user):
    client.get(f"/login_as/{user.id}", follow_redirects=True)


# ---------------------------------------------------------------------------
# Model property tests
# ---------------------------------------------------------------------------

class TestContractTotal:
    def test_normal(self, app):
        c = Contract(salesorder_id="SO-1", rate=2.5, quantity=100)
        assert c.total == 250.0

    def test_none_rate(self, app):
        c = Contract(salesorder_id="SO-2", rate=None, quantity=50)
        assert c.total == 0

    def test_none_quantity(self, app):
        c = Contract(salesorder_id="SO-3", rate=3.0, quantity=None)
        assert c.total == 0

    def test_both_none(self, app):
        c = Contract(salesorder_id="SO-4", rate=None, quantity=None)
        assert c.total == 0

    def test_zero_rate(self, app):
        c = Contract(salesorder_id="SO-5", rate=0.0, quantity=500)
        assert c.total == 0.0


class TestUserIsAdmin:
    def test_admin_role(self, app):
        u = User(email="a@a.com", role="admin")
        assert u.is_admin is True

    def test_broker_role(self, app):
        u = User(email="b@b.com", role="broker")
        assert u.is_admin is False

    def test_empty_role(self, app):
        u = User(email="c@c.com", role="")
        assert u.is_admin is False


# ---------------------------------------------------------------------------
# safe_float tests
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_numeric_string(self, app):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_integer_string(self, app):
        assert _safe_float("10") == 10.0

    def test_none(self, app):
        assert _safe_float(None) is None

    def test_empty_string(self, app):
        assert _safe_float("") is None

    def test_string_none(self, app):
        assert _safe_float("None") is None

    def test_already_float(self, app):
        assert _safe_float(1.5) == 1.5

    def test_garbage(self, app):
        assert _safe_float("abc") is None


# ---------------------------------------------------------------------------
# upsert_contract_from_zoho tests
# ---------------------------------------------------------------------------

def _minimal_detail(salesorder_id="SO-100", **overrides):
    d = {
        "salesorder_id": salesorder_id,
        "salesorder_number": "Q-001",
        "status": "open",
        "last_modified_time": "2025-01-01T00:00:00+0000",
        "date": "2025-01-01",
        "shipment_date": "2025-06-01",
        "customer_id": "CUST-1",
        "customer_name": "Acme Corp",
        "salesperson_name": "Alice",
        "salesperson_id": "EMP-1",
        "location_id": "LOC-1",
        "location_name": "Head Office",
        "reference_number": "BK-001",
        "notes": "Test notes",
        "terms": "Net 30",
        "custom_fields": [],
        "line_items": [
            {"item_id": "ITEM-1", "name": "Wheat", "quantity": 1000.0, "rate": 0.05}
        ],
    }
    d.update(overrides)
    return d


class TestUpsertContractFromZoho:
    def test_inserts_new_contract(self, app):
        detail = _minimal_detail("SO-NEW")
        upsert_contract_from_zoho(detail)
        c = Contract.query.get("SO-NEW")
        assert c is not None
        assert c.salesorder_number == "Q-001"
        assert c.customer_name == "Acme Corp"

    def test_updates_existing_contract(self, app):
        db.session.add(Contract(salesorder_id="SO-UPD", salesorder_number="OLD", customer_name="Old Name"))
        db.session.commit()
        detail = _minimal_detail("SO-UPD", salesorder_number="NEW", customer_name="New Name")
        upsert_contract_from_zoho(detail)
        c = Contract.query.get("SO-UPD")
        assert c.salesorder_number == "NEW"
        assert c.customer_name == "New Name"

    def test_maps_line_item_fields(self, app):
        detail = _minimal_detail("SO-LI")
        upsert_contract_from_zoho(detail)
        c = Contract.query.get("SO-LI")
        assert c.item_id == "ITEM-1"
        assert c.item_name == "Wheat"
        assert c.quantity == 1000.0
        assert c.rate == pytest.approx(0.05)

    def test_empty_line_items(self, app):
        detail = _minimal_detail("SO-NOLI", line_items=[])
        upsert_contract_from_zoho(detail)
        c = Contract.query.get("SO-NOLI")
        assert c.item_id == ""
        assert c.quantity is None

    def test_custom_field_mapping(self, app):
        detail = _minimal_detail("SO-CF", custom_fields=[
            {"api_name": "cf_buyer", "value": "BuyerCo"},
            {"api_name": "cf_item_contract_price", "value": "250.00"},
            {"api_name": "cf_uom", "value": "MT"},
            {"api_name": "cf_split_percentage", "value": "0.25"},
        ])
        upsert_contract_from_zoho(detail)
        c = Contract.query.get("SO-CF")
        assert c.cf_buyer == "BuyerCo"
        assert c.cf_item_contract_price == "250.00"
        assert c.cf_uom == "MT"
        assert c.cf_split_percentage == pytest.approx(0.25)

    def test_cf_buyer_id_resolved_from_customer_table(self, app):
        db.session.add(Customer(customer_id="CUST-B", customer_name="BuyerCo"))
        db.session.commit()
        detail = _minimal_detail("SO-BID", custom_fields=[
            {"api_name": "cf_buyer", "value": "BuyerCo"},
        ])
        upsert_contract_from_zoho(detail)
        c = Contract.query.get("SO-BID")
        assert c.cf_buyer_id == "CUST-B"

    def test_cf_buyer_id_none_when_no_matching_customer(self, app):
        detail = _minimal_detail("SO-BNOMATCH", custom_fields=[
            {"api_name": "cf_buyer", "value": "UnknownBuyer"},
        ])
        upsert_contract_from_zoho(detail)
        c = Contract.query.get("SO-BNOMATCH")
        assert c.cf_buyer_id is None

    def test_cf_buyer_id_none_when_no_buyer(self, app):
        detail = _minimal_detail("SO-NOBUYER")
        upsert_contract_from_zoho(detail)
        c = Contract.query.get("SO-NOBUYER")
        assert c.cf_buyer_id is None

    def test_no_op_on_missing_salesorder_id(self, app):
        upsert_contract_from_zoho({"salesorder_number": "ghost"})
        assert Contract.query.count() == 0

    def test_empty_price_stored_as_blank(self, app):
        detail = _minimal_detail("SO-SF", custom_fields=[
            {"api_name": "cf_item_contract_price", "value": ""},
        ])
        upsert_contract_from_zoho(detail)
        c = Contract.query.get("SO-SF")
        assert c.cf_item_contract_price == ""

    def test_local_fields_preserved_on_update(self, app):
        """in_network and buyer_reference must not be overwritten by upsert."""
        db.session.add(Contract(
            salesorder_id="SO-LOCAL",
            in_network=True,
            buyer_reference="BR-99"
        ))
        db.session.commit()
        upsert_contract_from_zoho(_minimal_detail("SO-LOCAL"))
        c = Contract.query.get("SO-LOCAL")
        assert c.in_network is True
        assert c.buyer_reference == "BR-99"


# ---------------------------------------------------------------------------
# contract_to_form_data_local tests
# ---------------------------------------------------------------------------

class TestContractToFormDataLocal:
    def _make_contract(self, **kwargs):
        defaults = dict(
            salesorder_id="SO-FD",
            customer_id="CUST-1",
            cf_buyer_id="CUST-2",
            cf_buyer="BuyerCo",
            shipment_date="2025-06-01",
            notes="notes",
            terms="net 30",
            item_id="ITEM-1",
            rate=0.05,
            quantity=500.0,
            cf_item_contract_price="250.00",
            cf_trnspname="Truck",
            cf_uom="MT",
            cf_customer_ref="REF-1",
            cf_co_broker="Bob",
            cf_co_brokerage_rate=0.02,
            location_id="LOC-1",
            location_name="Head Office",
        )
        defaults.update(kwargs)
        return Contract(**defaults)

    def test_basic_fields(self, app):
        c = self._make_contract()
        data = contract_to_form_data_local(c)
        assert data["seller"] == "CUST-1"
        assert data["buyer"] == "CUST-2"
        assert data["commodity"] == "ITEM-1"
        assert data["commission_rate"] == pytest.approx(0.05)
        assert data["quantity"] == pytest.approx(500.0)
        assert data["uom"] == "MT"

    def test_buyer_resolved_from_db_when_id_missing(self, app):
        db.session.add(Customer(customer_id="CUST-B", customer_name="BuyerCo"))
        db.session.commit()
        c = self._make_contract(cf_buyer_id=None, cf_buyer="BuyerCo")
        data = contract_to_form_data_local(c)
        assert data["buyer"] == "CUST-B"

    def test_buyer_empty_when_unresolvable(self, app):
        c = self._make_contract(cf_buyer_id=None, cf_buyer="Ghost")
        data = contract_to_form_data_local(c)
        assert data["buyer"] == ""

    def test_shipping_date_end_falls_back_to_cf(self, app):
        c = self._make_contract(shipment_date=None, cf_shipment_end_date="2025-09-01")
        data = contract_to_form_data_local(c)
        assert data["shipping_date_end"] == "2025-09-01"

    def test_contract_date_always_blank(self, app):
        """Intentional: duplicates should not copy the date."""
        c = self._make_contract()
        data = contract_to_form_data_local(c)
        assert data["contract_date"] == ""


# ---------------------------------------------------------------------------
# check_task_reactivity tests
# ---------------------------------------------------------------------------

class TestCheckTaskReactivity:
    def _setup_task(self, salesorder_id, books_field, status, completed_value):
        template = TaskTemplate(
            country="Boulder", order=1, title="T", books_field=books_field
        )
        db.session.add(template)
        db.session.flush()
        task = Task(
            books_sales_order_id=salesorder_id,
            template_id=template.id,
            status=status,
            completed_value=completed_value,
        )
        db.session.add(task)
        db.session.commit()
        return task

    def test_reopens_complete_task_when_field_changed(self, app):
        task = self._setup_task("SO-1", "shipment_date", "complete", "2025-01-01")
        check_task_reactivity("SO-1", {"shipment_date": "2025-06-01"})
        db.session.refresh(task)
        assert task.status == "pending"

    def test_leaves_complete_task_when_field_unchanged(self, app):
        task = self._setup_task("SO-2", "shipment_date", "complete", "2025-01-01")
        check_task_reactivity("SO-2", {"shipment_date": "2025-01-01"})
        db.session.refresh(task)
        assert task.status == "complete"

    def test_ignores_pending_tasks(self, app):
        task = self._setup_task("SO-3", "shipment_date", "pending", "2025-01-01")
        check_task_reactivity("SO-3", {"shipment_date": "2025-06-01"})
        db.session.refresh(task)
        assert task.status == "pending"

    def test_ignores_task_with_no_books_field(self, app):
        task = self._setup_task("SO-4", "", "complete", "old")
        check_task_reactivity("SO-4", {"shipment_date": "2025-06-01"})
        db.session.refresh(task)
        assert task.status == "complete"

    def test_no_tasks_no_error(self, app):
        check_task_reactivity("SO-NONE", {"shipment_date": "2025-06-01"})

    def test_changed_field_not_in_changed_dict_does_not_reopen(self, app):
        task = self._setup_task("SO-5", "shipment_date", "complete", "2025-01-01")
        check_task_reactivity("SO-5", {"other_field": "irrelevant"})
        db.session.refresh(task)
        assert task.status == "complete"


# ---------------------------------------------------------------------------
# generate_tasks tests
# ---------------------------------------------------------------------------

class TestGenerateTasks:
    def _seed_templates(self, country="Boulder", count=3):
        for i in range(count):
            db.session.add(TaskTemplate(
                country=country, order=i, title=f"Task {i}", books_field=""
            ))
        db.session.commit()

    def test_generates_one_task_per_template(self, app):
        self._seed_templates(count=3)
        generate_tasks("SO-GEN", country="Boulder")
        tasks = Task.query.filter_by(books_sales_order_id="SO-GEN").all()
        assert len(tasks) == 3

    def test_all_tasks_start_pending(self, app):
        self._seed_templates(count=2)
        generate_tasks("SO-PEND", country="Boulder")
        tasks = Task.query.filter_by(books_sales_order_id="SO-PEND").all()
        assert all(t.status == "pending" for t in tasks)

    def test_idempotent_does_not_duplicate(self, app):
        self._seed_templates(count=2)
        generate_tasks("SO-IDEM", country="Boulder")
        generate_tasks("SO-IDEM", country="Boulder")
        tasks = Task.query.filter_by(books_sales_order_id="SO-IDEM").all()
        assert len(tasks) == 2

    def test_no_templates_no_tasks(self, app):
        generate_tasks("SO-EMPTY", country="Boulder")
        assert Task.query.count() == 0

    def test_country_filter(self, app):
        self._seed_templates("Boulder", 2)
        self._seed_templates("Argentina", 3)
        generate_tasks("SO-ARG", country="Argentina")
        tasks = Task.query.filter_by(books_sales_order_id="SO-ARG").all()
        assert len(tasks) == 3


# ---------------------------------------------------------------------------
# Route: authentication / access control
# ---------------------------------------------------------------------------

class TestAuthRoutes:
    def test_home_unauthenticated_redirects(self, client):
        resp = client.get("/", follow_redirects=False)
        # Flask-Login redirects (302) or returns 401 depending on version/config
        assert resp.status_code in (302, 401)

    def test_home_authenticated(self, client, broker_user):
        _login(client, broker_user)
        resp = client.get("/")
        assert resp.status_code == 200

    def test_admin_page_blocks_broker(self, client, broker_user):
        _login(client, broker_user)
        resp = client.get("/admin/users", follow_redirects=False)
        # admin_required redirects to /
        assert resp.status_code == 302

    def test_admin_page_allows_admin(self, client, admin_user):
        _login(client, admin_user)
        resp = client.get("/admin/users")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Route: toggle_decline
# ---------------------------------------------------------------------------

class TestToggleDecline:
    def test_toggles_to_true(self, client, broker_user, app):
        db.session.add(Contract(salesorder_id="SO-D1", is_declined=False))
        db.session.commit()
        _login(client, broker_user)
        resp = client.post("/contracts/SO-D1/decline")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["is_declined"] is True

    def test_toggles_back_to_false(self, client, broker_user, app):
        db.session.add(Contract(salesorder_id="SO-D2", is_declined=True))
        db.session.commit()
        _login(client, broker_user)
        resp = client.post("/contracts/SO-D2/decline")
        assert resp.get_json()["is_declined"] is False

    def test_404_on_missing_contract(self, client, broker_user, app):
        _login(client, broker_user)
        resp = client.post("/contracts/GHOST/decline")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Route: shipments
# ---------------------------------------------------------------------------

class TestShipmentRoutes:
    def test_add_shipment(self, client, broker_user, app):
        db.session.add(Contract(salesorder_id="SO-S1"))
        db.session.commit()
        _login(client, broker_user)
        resp = client.post(
            "/contracts/SO-S1/shipments/add",
            json={"booking_number": "BK-99", "quantity": "500"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert Shipment.query.count() == 1

    def test_add_shipment_no_quantity(self, client, broker_user, app):
        db.session.add(Contract(salesorder_id="SO-S2"))
        db.session.commit()
        _login(client, broker_user)
        resp = client.post(
            "/contracts/SO-S2/shipments/add",
            json={"booking_number": "BK-100"},
        )
        assert resp.status_code == 200
        s = Shipment.query.first()
        assert s.quantity is None

    def test_delete_shipment(self, client, broker_user, app):
        s = Shipment(books_sales_order_id="SO-S3", booking_number="BK-DEL")
        db.session.add(s)
        db.session.commit()
        sid = s.id
        _login(client, broker_user)
        resp = client.post(f"/contracts/shipments/{sid}/delete")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert Shipment.query.get(sid) is None

    def test_delete_shipment_404(self, client, broker_user):
        _login(client, broker_user)
        resp = client.post("/contracts/shipments/9999/delete")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Route: admin user management
# ---------------------------------------------------------------------------

class TestAdminUserManagement:
    def test_create_user(self, client, admin_user, app):
        _login(client, admin_user)
        resp = client.post("/admin/users/create", data={
            "email": "new@test.com", "display_name": "New", "role": "broker"
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert User.query.filter_by(email="new@test.com").first() is not None

    def test_create_duplicate_user_rejected(self, client, admin_user, app):
        db.session.add(User(email="dup@test.com", role="broker"))
        db.session.commit()
        _login(client, admin_user)
        client.post("/admin/users/create", data={
            "email": "dup@test.com", "display_name": "Dup", "role": "broker"
        })
        assert User.query.filter_by(email="dup@test.com").count() == 1

    def test_create_user_no_email_rejected(self, client, admin_user):
        _login(client, admin_user)
        client.post("/admin/users/create", data={"email": "", "role": "broker"})
        # only admin_user exists
        assert User.query.count() == 1

    def test_update_role(self, client, admin_user, app):
        target = User(email="flip@test.com", role="broker")
        db.session.add(target)
        db.session.commit()
        _login(client, admin_user)
        client.post(f"/admin/users/{target.id}/role", data={"role": "admin"})
        db.session.refresh(target)
        assert target.role == "admin"

    def test_update_role_invalid_rejected(self, client, admin_user, app):
        target = User(email="keep@test.com", role="broker")
        db.session.add(target)
        db.session.commit()
        _login(client, admin_user)
        client.post(f"/admin/users/{target.id}/role", data={"role": "superuser"})
        db.session.refresh(target)
        assert target.role == "broker"

    def test_delete_user(self, client, admin_user, app):
        target = User(email="bye@test.com", role="broker")
        db.session.add(target)
        db.session.commit()
        tid = target.id
        _login(client, admin_user)
        client.post(f"/admin/users/{tid}/delete")
        assert db.session.get(User, tid) is None

    def test_cannot_delete_self(self, client, admin_user, app):
        _login(client, admin_user)
        client.post(f"/admin/users/{admin_user.id}/delete")
        assert db.session.get(User, admin_user.id) is not None