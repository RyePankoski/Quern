import os
from datetime import datetime

from flask import Flask, render_template, request, redirect, flash, send_file, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from core import zoho
from core.models import db, Customer, Item, Employee, Task, TaskTemplate, User, AuditLog, Contract, Shipment, \
    BrokerCommission, ContractNote
from core.pdf import generate_contract_pdf, generate_contract_docx
from core.tasks import generate_tasks, check_task_reactivity
from core.zoho import get_sales_orders, sync_employees, sync_items, sync_customers
from core.zoho import sync_customers_page, sync_contracts_page

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///quern.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.getenv("SECRET_KEY")
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect('/')
        return f(*args, **kwargs)
    return decorated


# Routes to move to a new page

@app.route('/')
@login_required
def home():
    return render_template('home.html')


@app.route('/items')
@login_required
def items_view():
    items = Item.query.order_by(Item.item_name).all()
    return render_template('items.html', items=items)


@app.route('/items/<item_id>')
@login_required
def item_detail(item_id):
    item = Item.query.get(item_id)
    if not item:
        flash('Item not found.', 'danger')
        return redirect('/items')

    # Use the item-filtered endpoint instead of fetching all orders and
    # scanning line items — the list endpoint does not return line_items,
    # so the old approach always produced zero results.
    contracts = Contract.query.filter_by(item_id=item_id).order_by(Contract.date.desc()).all()
    return render_template('item_detail.html', item=item, contracts=contracts)


@app.route('/counterparties')
@login_required
def counterparties():
    customers = Customer.query.order_by(Customer.customer_name).all()
    return render_template('counterparties.html', customers=customers)


@app.route('/counterparties/<customer_id>')
@login_required
def counterparty_detail(customer_id):
    customer = Customer.query.get(customer_id)
    if not customer:
        flash('Counterparty not found.', 'danger')
        return redirect('/counterparties')

    contracts = Contract.query.filter(
        db.or_(Contract.customer_id == customer_id, Contract.cf_buyer_id == customer_id)
    ).order_by(Contract.date.desc()).all()

    return render_template('counterparty_detail.html', customer=customer, contracts=contracts)


@app.route('/employees/<employee_id>/office', methods=['POST'])
@login_required
def update_employee_office(employee_id):
    employee = Employee.query.get(employee_id)
    if not employee:
        return {'ok': False, 'error': 'Employee not found'}, 404
    data = request.get_json()
    employee.office = data.get('office', '').strip() or None
    db.session.commit()
    return {'ok': True}


@app.route('/employees/<employee_id>/active', methods=['POST'])
@login_required
def update_employee_active(employee_id):
    employee = Employee.query.get(employee_id)
    if not employee:
        return {'ok': False, 'error': 'Employee not found'}, 404
    data = request.get_json()
    employee.is_active = bool(data.get('is_active', True))
    db.session.commit()
    return {'ok': True}


@app.route('/employees')
@login_required
def employees_view():
    employees = Employee.query.order_by(Employee.employee_name).all()
    return render_template('employees.html', employees=employees)


@app.route('/new_contract')
@login_required
def new_contract():
    items = Item.query.filter_by(is_active=True).order_by(Item.item_name).all()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.customer_name).all()
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.employee_name).all()
    locations = zoho.get_locations()
    prefill = None
    prefill_brokers = []
    duplicate_id = request.args.get('duplicate')

    if duplicate_id:
        source = Contract.query.get(duplicate_id)
        if source:
            prefill = zoho.contract_to_form_data_local(source)
            prefill_brokers = BrokerCommission.query.filter_by(books_sales_order_id=duplicate_id).all()
            if not prefill_brokers and source.salesperson_id:
                fallback_emp = Employee.query.filter_by(salesperson_id=source.salesperson_id).first()
                if fallback_emp:
                    prefill_brokers = [type('obj', (object,), {
                        'employee_id': fallback_emp.employee_id,
                        'percentage': 100.0
                    })()]


    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('new_contract.html', items=items, customers=customers, employees=employees, prefill=prefill,
                           prefill_brokers=prefill_brokers, locations=locations, today=today)


@app.route('/bulk_edit')
@login_required
def bulk_edit():
    contracts = Contract.query.order_by(Contract.date.desc()).all()
    return render_template('bulk_edit.html', contracts=contracts)


@app.route('/contracts')
@login_required
def contracts():
    contracts = Contract.query.order_by(Contract.date.desc()).all()
    return render_template('contracts.html', contracts=contracts, page=1)


@app.route('/contracts/<salesorder_id>')
@login_required
def contract_detail(salesorder_id):
    c = Contract.query.get(salesorder_id)
    if not c:
        flash('Contract not found.', 'danger')
        return redirect('/contracts')

    # Build a dict that mirrors the old Zoho response shape for the template
    contract = {
        'salesorder_id': c.salesorder_id,
        'salesorder_number': c.salesorder_number,
        'status': c.status,
        'date': c.date,
        'shipment_date': c.shipment_date,
        'customer_id': c.customer_id,
        'customer_name': c.customer_name,
        'salesperson_name': c.salesperson_name,
        'salesperson_id': c.salesperson_id,
        'location_id': c.location_id,
        'location_name': c.location_name,
        'notes': c.notes,
        'terms': c.terms,
        'line_items': [{
            'item_id': c.item_id,
            'name': c.item_name,
            'rate': c.rate,
            'quantity': c.quantity,
        }] if c.item_id else [],
        'custom': {
            'cf_buyer': c.cf_buyer,
            'cf_item_contract_price': c.cf_item_contract_price,
            'cf_trnspname': c.cf_trnspname,
            'cf_uom': c.cf_uom,
            'cf_customer_ref': c.cf_customer_ref,
            'cf_co_broker': c.cf_co_broker,
            'cf_co_brokerage_rate': c.cf_co_brokerage_rate,
            'cf_split_broker': c.cf_split_broker,
            'cf_split_percentage': c.cf_split_percentage,
            'cf_vessel_name': c.cf_vessel_name,
            'cf_shipment_end_date': c.cf_shipment_end_date,
        },
    }

    customers = Customer.query.order_by(Customer.customer_name).all()
    items = Item.query.order_by(Item.item_name).all()

    tasks = Task.query.filter_by(
        books_sales_order_id=salesorder_id
    ).join(TaskTemplate).order_by(TaskTemplate.order).all()

    shipments = Shipment.query.filter_by(books_sales_order_id=salesorder_id).all()
    commissions = BrokerCommission.query.filter_by(books_sales_order_id=salesorder_id).all()
    notes = ContractNote.query.filter_by(books_sales_order_id=salesorder_id).order_by(ContractNote.created_at).all()
    employees = Employee.query.all()
    employee_map = {e.employee_id: e.employee_name for e in employees}

    salesperson_employee = next(
        (e for e in employees if e.salesperson_id == c.salesperson_id), None
    )

    return render_template('contract_detail.html',
                           contract=contract, customers=customers, items=items,
                           tasks=tasks, meta=c, shipments=shipments,
                           commissions=commissions, notes=notes, employee_map=employee_map,
                           salesperson_employee=salesperson_employee)


@app.route('/tasks')
@login_required
def tasks_view():
    from sqlalchemy import func
    task_counts = db.session.query(
        Task.books_sales_order_id,
        func.count(Task.id).label('total'),
        func.sum(db.case((Task.status == 'pending', 1), else_=0)).label('pending')
    ).group_by(Task.books_sales_order_id).all()

    contract_map = {c.salesorder_id: c for c in Contract.query.all()}

    task_list = []
    for row in task_counts:
        contract = contract_map.get(row.books_sales_order_id)
        task_list.append({
            'salesorder_id': row.books_sales_order_id,
            'salesorder_number': contract.salesorder_number if contract else row.books_sales_order_id,
            'location_name': contract.location_name if contract else '',
            'total': row.total,
            'pending': row.pending
        })

    task_list.sort(key=lambda x: x['pending'], reverse=True)
    return render_template('tasks.html', task_list=task_list)


@app.route('/admin/audit')
@login_required
@admin_required
def audit_log_view():
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(200).all()
    return render_template('admin_audit.html', logs=logs)


# Submission/Api Call

@app.route('/submit_contract', methods=['POST'])
@login_required
def submit_contract_route():
    form_data = request.form.to_dict(flat=True)

    # Resolve buyer ID → name for Books custom field
    buyer_id = form_data.get('buyer', '')
    buyer = Customer.query.get(buyer_id)
    form_data['buyer_name'] = buyer.customer_name if buyer else ''

    # First broker → salesperson_employee_id, second → second_broker_employee_id
    broker_employees = request.form.getlist('broker_employee[]')
    broker_percentages = request.form.getlist('broker_percentage[]')
    form_data['salesperson_employee_id'] = broker_employees[0] if len(broker_employees) > 0 else ''
    form_data['second_broker_employee_id'] = broker_employees[1] if len(broker_employees) > 1 else ''
    form_data['second_broker_percentage'] = broker_percentages[1] if len(broker_percentages) > 1 else ''

    # Concatenate booking numbers into a comma-separated string for customer_notes
    booking_numbers = request.form.getlist('booking_number[]')
    form_data['booking_numbers_concat'] = ','.join(b for b in booking_numbers if b.strip())

    result = zoho.submit_contract(form_data)
    if result.get('code', 0) == 0:
        salesorder_id = result['salesorder']['salesorder_id']
        salesorder_number = result['salesorder']['salesorder_number']

        zoho.upsert_contract_from_zoho(result['salesorder'])

        office = request.form.get('location_name', 'Head Office')
        generate_tasks(salesorder_id, country=office)

        meta = Contract.query.get(salesorder_id)
        in_network_val = request.form.get('in_network')
        meta.in_network = True if in_network_val == 'true' else False if in_network_val == 'false' else None
        meta.buyer_reference = request.form.get('buyer_reference', '').strip() or None

        shipment_quantities = request.form.getlist('shipment_quantity[]')
        for booking, qty in zip(booking_numbers, shipment_quantities):
            if booking or qty:
                db.session.add(Shipment(
                    books_sales_order_id=salesorder_id,
                    booking_number=booking,
                    quantity=float(qty) if qty else None
                ))
        db.session.commit()

        employee_ids = request.form.getlist('broker_employee[]')
        percentages = request.form.getlist('broker_percentage[]')
        amounts = request.form.getlist('broker_amount[]')
        for emp_id, pct, amt in zip(employee_ids, percentages, amounts):
            if emp_id and pct:
                db.session.add(BrokerCommission(
                    books_sales_order_id=salesorder_id,
                    employee_id=emp_id,
                    percentage=float(pct),
                    amount=float(amt) if amt else 0.0
                ))
        db.session.commit()

        log = AuditLog(
            user=current_user.email,
            method='POST',
            path='/submit_contract',
            salesorder_id=salesorder_id,
            timestamp=datetime.utcnow()
        )
        db.session.add(log)
        db.session.commit()
        return redirect(f'/submit_success/{salesorder_id}?number={salesorder_number}')
    else:
        flash(f"Submission failed: {result.get('message', 'Unknown error')}", 'danger')
        return redirect('/new_contract')


@app.route('/bulk_edit/<salesorder_id>', methods=['POST'])
@login_required
def bulk_edit_save(salesorder_id):
    data = request.get_json()
    field = data.get('field')
    value = data.get('value')

    allowed_fields = {
        # Zoho fields
        'quantity', 'commission_rate', 'seller_reference', 'shipping_date_end', 'contract_date',
        'uom', 'transportation', 'co_broker_name', 'vessel_name',
        'commodity_rate', 'co_brokerage_rate', 'delivery_notes', 'terms',
        # Local-only fields
        'buyer_reference', 'in_network', 'packing',
    }
    if field not in allowed_fields:
        return {'ok': False, 'error': 'Invalid field'}, 400

    # Local-only fields — save to Contract and return early, no Zoho call
    if field in ('buyer_reference', 'in_network', 'packing'):
        meta = Contract.query.get(salesorder_id)
        if not meta:
            meta = Contract(salesorder_id=salesorder_id)
            db.session.add(meta)
        if field == 'buyer_reference':
            meta.buyer_reference = value.strip() or None
        elif field == 'in_network':
            meta.in_network = True if value == 'true' else False if value == 'false' else None
        elif field == 'packing':
            meta.packing = value.strip() or None
        db.session.commit()
        return {'ok': True}

    contract = zoho.get_sales_order(salesorder_id)
    form_data = zoho.contract_to_form_data(contract)
    form_data[field] = value

    # Preserve salesperson: look up the employee whose salesperson_id matches the contract's
    salesperson_zoho_id = contract.get('salesperson_id', '')
    if salesperson_zoho_id:
        matching_emp = Employee.query.filter_by(salesperson_id=salesperson_zoho_id).first()
        form_data['salesperson_employee_id'] = matching_emp.employee_id if matching_emp else ''
    else:
        form_data['salesperson_employee_id'] = ''


    # Rebuild booking numbers from local Shipment table so cf_custom_customer_notes is preserved
    local_shipments = Shipment.query.filter_by(books_sales_order_id=salesorder_id).all()
    form_data['booking_numbers_concat'] = ','.join(s.booking_number for s in local_shipments if s.booking_number)

    result = zoho.update_contract(salesorder_id, form_data)
    if result.get('code', 0) == 0:
        check_task_reactivity(salesorder_id, {field: value})
        zoho.upsert_contract_from_zoho(result['salesorder'])
        return {'ok': True}
    else:
        return {'ok': False, 'error': result.get('message', 'Unknown error')}, 500


@app.route('/contracts/<salesorder_id>/update', methods=['POST'])
@login_required
def update_contract(salesorder_id):
    form_data = request.form.to_dict(flat=True)

    buyer_id = form_data.get('buyer', '')
    buyer = Customer.query.get(buyer_id)
    form_data['buyer_name'] = buyer.customer_name if buyer else ''

    broker_employees = request.form.getlist('broker_employee[]')
    broker_percentages = request.form.getlist('broker_percentage[]')
    form_data['salesperson_employee_id'] = broker_employees[0] if len(broker_employees) > 0 else ''
    form_data['second_broker_employee_id'] = broker_employees[1] if len(broker_employees) > 1 else ''
    form_data['second_broker_percentage'] = broker_percentages[1] if len(broker_percentages) > 1 else ''

    booking_numbers = request.form.getlist('booking_number[]')
    form_data['booking_numbers_concat'] = ','.join(b for b in booking_numbers if b.strip())

    result = zoho.update_contract(salesorder_id, form_data)
    if result.get('code', 0) == 0:
        check_task_reactivity(salesorder_id, form_data)

        zoho.upsert_contract_from_zoho(result['salesorder'])

        meta = Contract.query.get(salesorder_id)
        in_network_val = request.form.get('in_network')
        meta.in_network = True if in_network_val == 'true' else False if in_network_val == 'false' else None
        meta.buyer_reference = request.form.get('buyer_reference', '').strip() or None

        Shipment.query.filter_by(books_sales_order_id=salesorder_id).delete()
        shipment_quantities = request.form.getlist('shipment_quantity[]')
        for booking, qty in zip(booking_numbers, shipment_quantities):
            if booking or qty:
                db.session.add(Shipment(
                    books_sales_order_id=salesorder_id,
                    booking_number=booking,
                    quantity=float(qty) if qty else None
                ))
        db.session.commit()

        BrokerCommission.query.filter_by(books_sales_order_id=salesorder_id).delete()
        employee_ids = request.form.getlist('broker_employee[]')
        percentages = request.form.getlist('broker_percentage[]')
        amounts = request.form.getlist('broker_amount[]')
        for emp_id, pct, amt in zip(employee_ids, percentages, amounts):
            if emp_id and pct:
                db.session.add(BrokerCommission(
                    books_sales_order_id=salesorder_id,
                    employee_id=emp_id,
                    percentage=float(pct),
                    amount=float(amt) if amt else 0.0
                ))
        db.session.commit()

        salesorder_number = result['salesorder']['salesorder_number']
        return redirect(f'/submit_success/{salesorder_id}?number={salesorder_number}&action=updated')
    else:
        flash(f"Update failed: {result.get('message', 'Unknown error')}", 'danger')
        return redirect(request.referrer or '/contracts')


# Security related

@app.before_request
def audit_log():
    if request.method != 'POST':
        return
    if not current_user.is_authenticated:
        return

    # Only log contract-related actions
    path = request.path
    contract_paths = ['/contracts/', '/bulk_edit/']
    if not any(path.startswith(p) for p in contract_paths):
        return

    # Try to extract salesorder ID from path
    parts = path.strip('/').split('/')
    salesorder_id = parts[1] if len(parts) >= 2 and parts[0] == 'contracts' else None

    log = AuditLog(
        user=current_user.email,
        method=request.method,
        path=path,
        salesorder_id=salesorder_id,
        timestamp=datetime.utcnow()
    )
    db.session.add(log)
    db.session.commit()


# User auth and login routes


@app.route('/login')
def login():
    """Kick off Azure AD OAuth flow."""
    import secrets
    from core.auth import build_auth_url
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    return redirect(build_auth_url(state))


@app.route('/auth/callback')
def auth_callback():
    """Handle the OAuth callback from Azure AD."""
    from core.auth import acquire_token_by_code

    # If the user is already logged in, this is a duplicate callback
    # (browser prefetch, retry, etc). Don't run the flow again.
    if current_user.is_authenticated:
        return redirect('/')

    # CSRF check
    if request.args.get('state') != session.pop('oauth_state', None):
        flash('Authentication state mismatch. Please try again.', 'danger')
        return redirect('/login')

    # Azure AD error (e.g. user cancelled)
    if 'error' in request.args:
        flash(f"Sign-in failed: {request.args.get('error_description', request.args.get('error'))}", 'danger')
        return redirect('/login')

    code = request.args.get('code')
    if not code:
        flash('No authorization code returned.', 'danger')
        return redirect('/login')

    result = acquire_token_by_code(code)
    if 'error' in result:
        flash(f"Token exchange failed: {result.get('error_description', result.get('error'))}", 'danger')
        return redirect('/login')

    claims = result.get('id_token_claims', {})
    email = (claims.get('preferred_username') or claims.get('email') or '').strip().lower()
    if not email:
        flash('Microsoft account did not return an email.', 'danger')
        return redirect('/login')

    # Local gatekeeping: account must be pre-provisioned in Quern.
    user = User.query.filter_by(email=email).first()
    if not user:
        flash(f'{email} is not authorized for Quern. Contact an admin.', 'danger')
        return redirect('/login')

    # Optionally backfill display_name from the token on first login
    if not user.display_name and claims.get('name'):
        user.display_name = claims.get('name')
        db.session.commit()

    login_user(user)
    return redirect('/')


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect('/logged-out')


@app.route('/logged-out')
def logged_out():
    return render_template('logged_out.html')


# Admin task template creation.

@app.route('/admin/templates')
@login_required
@admin_required
def admin_templates():
    templates = TaskTemplate.query.order_by(TaskTemplate.country, TaskTemplate.order).all()
    return render_template('admin_templates.html', templates=templates)


@app.route('/admin/templates/create', methods=['POST'])
@login_required
@admin_required
def create_template():
    order = request.form.get('order', '').strip()
    template = TaskTemplate(
        country=request.form.get('country'),
        order=int(order) if order else 0,
        title=request.form.get('title'),
        description=request.form.get('description'),
        books_field=request.form.get('books_field')
    )
    db.session.add(template)
    db.session.commit()
    return redirect('/admin/templates')


@app.route('/admin/templates/<int:template_id>/update', methods=['POST'])
@login_required
@admin_required
def update_template(template_id):
    template = TaskTemplate.query.get(template_id)
    if not template:
        flash('Template not found.', 'danger')
        return redirect('/admin/templates')
    template.country = request.form.get('country')
    template.order = int(request.form.get('order', 0))
    template.title = request.form.get('title')
    template.description = request.form.get('description')
    template.books_field = request.form.get('books_field')
    db.session.commit()
    return redirect('/admin/templates')


@app.route('/admin/templates/<int:template_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_template(template_id):
    template = TaskTemplate.query.get(template_id)
    if not template:
        flash('Template not found.', 'danger')
        return redirect('/admin/templates')
    db.session.delete(template)
    db.session.commit()
    return redirect('/admin/templates')


# Sub-screens like submission success

@app.route('/submit_success/<salesorder_id>')
@login_required
def submit_success(salesorder_id):
    salesorder_number = request.args.get('number', 'Unknown')
    return render_template('submit_success.html', salesorder_id=salesorder_id, salesorder_number=salesorder_number)


# Sub-processes like confirming tasks or seeding tasks, these are app sided

@app.route('/seed_tasks')
def seed_tasks():
    if TaskTemplate.query.first():
        return "Templates already seeded, skipping."
    templates = [
        TaskTemplate(country='Boulder', order=1, title='Task 1 - Vessel Name',
                     description='Confirm the vessel name with the counterparty.', books_field='vessel_name'),
        TaskTemplate(country='Boulder', order=2, title='Task 2 - Commodity Price',
                     description='Confirm the agreed commodity price.', books_field='commodity_rate'),
        TaskTemplate(country='Boulder', order=3, title='Task 3 - Quantity',
                     description='Confirm the quantity with the seller.', books_field='quantity'),
        TaskTemplate(country='Boulder', order=4, title='Task 4 - UOM',
                     description='Confirm the unit of measure.', books_field='uom'),
        TaskTemplate(country='Boulder', order=5, title='Task 5 - Shipping Date',
                     description='Confirm the expected shipping date.', books_field='shipping_date'),
    ]
    for t in templates:
        db.session.add(t)
    db.session.commit()
    return f"Seeded {len(templates)} task templates"


@app.route('/tasks/<int:task_id>/confirm', methods=['POST'])
@login_required
def confirm_task(task_id):
    data = request.get_json()
    task = Task.query.get(task_id)
    if not task:
        return {'ok': False, 'error': 'Task not found'}, 404
    value = data.get('completed_value', '')
    if value == 'yes':
        task.status = 'complete'
        task.completed_value = value
        task.completed_at = datetime.utcnow()
    else:
        task.status = 'pending'
        task.completed_value = None
        task.completed_at = None
    db.session.commit()
    return {'ok': True}


# Resource creation, like the contracts JSON


@app.route('/api/contracts')
@login_required
def contracts_json():
    # Load more is no longer needed — all contracts are local
    return {'contracts': [], 'page': 1}


# Dev page stuff

@app.route('/debug/contracts_list')
@login_required
def debug_contracts_list():
    orders = get_sales_orders(page=1)
    return orders[0] if orders else {}


@app.route('/debug/customers')
@login_required
def debug_customers():
    token = zoho.get_access_token()
    import requests
    response = requests.get(
        "https://www.zohoapis.com/books/v3/contacts",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": zoho.ORG_ID, "contact_type": "customer", "per_page": 1}
    )
    return response.json()


@app.route('/debug/items')
@login_required
def debug_items():
    token = zoho.get_access_token()
    import requests
    response = requests.get(
        "https://www.zohoapis.com/books/v3/items",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": zoho.ORG_ID, "per_page": 200}
    )
    return response.json()


@app.route('/dev')
@login_required
def dev_panel():
    return render_template('dev.html')


# TEMPORARY - remove after first deployment
@app.route('/init')
def init_db():
    db.create_all()
    wipe_tasks()
    seed_tasks()
    create_user()
    return {'result': 'DB initialized. Now hit /init/items, /init/customers, /init/employees in order.'}

@app.route('/init/items')
def init_items():
    sync_items()
    return {'result': 'Items synced.'}

@app.route('/init/customers')
def init_customers():
    sync_customers()
    return {'result': 'Customers synced.'}

@app.route('/init/employees')
def init_employees():
    sync_employees()
    return {'result': 'Employees synced.'}


@app.route('/init/customers/page')
def init_customers_page():
    page = request.args.get('page', 1, type=int)
    result = sync_customers_page(page)
    return {'has_more': result['has_more'], 'count': result['count'], 'page': page}


@app.route('/init/contracts/page')
def init_contracts_page():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', None, type=int)
    result = sync_contracts_page(page, limit=limit)
    return {'has_more': result['has_more'], 'count': result['count'], 'page': page}


@app.route('/init/incremental/page')
@login_required
def init_incremental_page():
    page = request.args.get('page', 1, type=int)
    result = zoho.incremental_sync_page(page)
    return {'has_more': result['has_more'], 'count': result['count'], 'page': page}


@app.route('/dev/action/<action>', methods=['POST'])
@login_required
def dev_action(action):
    with app.app_context():
        if action == 'wipe_tasks':
            result = wipe_tasks()
        elif action == 'seed_tasks':
            result = seed_tasks()
        elif action == 'sync_items':
            sync_items()
            result = 'Items synced.'
        elif action == 'sync_customers':
            sync_customers()
            result = 'Customers synced.'
        elif action == 'sync_employees':
            sync_employees()
            result = 'Employees synced.'
        elif action == 'create_user':
            result = create_user()
        elif action == 'wipe_audit':
            result = wipe_audit()
        elif action == 'wipe_users':
            result = wipe_users()
        elif action == 'first_time_startup':
            first_time_startup()
            result = 'First time startup complete.'
        else:
            result = f'Unknown action: {action}'
    return {'result': str(result)}


@app.route('/dev/debug/<target>')
@login_required
def dev_debug(target):
    if target == 'first_contract':
        result = debug_first_contract()
    elif target == 'locations':
        result = debug_locations()
    elif target == 'reporting_tags':
        result = zoho.debug_reporting_tags()
    else:
        result = {'error': f'Unknown debug target: {target}'}
    return result


@app.route('/debug_first_contract')
@login_required
def debug_first_contract():
    orders = get_sales_orders(page=1)
    if not orders:
        return {'error': 'No contracts found'}
    first_id = orders[0]['salesorder_id']
    contract = zoho.get_sales_order(first_id)
    return contract


@app.route('/debug_locations')
@login_required
def debug_locations():
    return {'locations': zoho.get_locations()}


# Local contract data

@app.route('/contracts/<salesorder_id>/meta', methods=['POST'])
@login_required
def save_contract_meta(salesorder_id):
    meta = Contract.query.get(salesorder_id)
    if not meta:
        meta = Contract(salesorder_id=salesorder_id)
        db.session.add(meta)

    in_network_val = request.form.get('in_network')
    if in_network_val == 'true':
        meta.in_network = True
    elif in_network_val == 'false':
        meta.in_network = False
    else:
        meta.in_network = None

    # Wipe and replace shipments
    Shipment.query.filter_by(books_sales_order_id=salesorder_id).delete()
    booking_numbers = request.form.getlist('booking_number[]')
    shipment_quantities = request.form.getlist('shipment_quantity[]')
    for booking, qty in zip(booking_numbers, shipment_quantities):
        if booking:
            qty_val = float(qty) if qty else None
            shipment = Shipment(
                books_sales_order_id=salesorder_id,
                booking_number=booking,
                quantity=qty_val
            )
            db.session.add(shipment)

    db.session.commit()
    return redirect(request.referrer or f'/contracts/{salesorder_id}')


@app.route('/contracts/<salesorder_id>/shipments/add', methods=['POST'])
@login_required
def add_shipment(salesorder_id):
    data = request.get_json()
    qty_val = data.get('quantity')
    shipment = Shipment(
        books_sales_order_id=salesorder_id,
        booking_number=data.get('booking_number', ''),
        quantity=float(qty_val) if qty_val else None
    )
    db.session.add(shipment)
    db.session.commit()
    return {'ok': True, 'id': shipment.id}


@app.route('/contracts/shipments/<int:shipment_id>/delete', methods=['POST'])
@login_required
def delete_shipment(shipment_id):
    shipment = Shipment.query.get(shipment_id)
    if not shipment:
        return {'ok': False}, 404
    db.session.delete(shipment)
    db.session.commit()
    return {'ok': True}


@app.route('/contracts/<salesorder_id>/pdf')
@login_required
def contract_pdf(salesorder_id):
    contract, data = _build_contract_data(salesorder_id)
    logo_path = os.path.join(app.root_path, 'static', 'img', 'logo_header.jpeg')
    buffer = generate_contract_pdf(data, logo_path)
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"{contract.get('salesorder_number', 'contract')}.pdf"
    )


@app.route('/contracts/<salesorder_id>/docx')
@login_required
def contract_docx(salesorder_id):
    contract, data = _build_contract_data(salesorder_id)
    logo_path = os.path.join(app.root_path, 'static', 'img', 'logo_header.jpeg')
    buffer = generate_contract_docx(data, logo_path)
    return send_file(
        buffer,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name=f"{contract.get('salesorder_number', 'contract')}.docx"
    )


@app.route('/contracts/<salesorder_id>/notes/add', methods=['POST'])
@login_required
def add_note(salesorder_id):
    body = request.form.get('body', '').strip()
    if not body:
        flash('Note cannot be empty.', 'warning')
        return redirect(f'/contracts/{salesorder_id}')
    note = ContractNote(
        books_sales_order_id=salesorder_id,
        author=current_user.display_name or current_user.email,
        body=body
    )
    db.session.add(note)
    db.session.commit()
    return redirect(f'/contracts/{salesorder_id}#notes')


@app.route('/contracts/notes/<int:note_id>/delete', methods=['POST'])
@login_required
def delete_note(note_id):
    note = ContractNote.query.get(note_id)
    if not note:
        return {'ok': False}, 404
    salesorder_id = note.books_sales_order_id
    db.session.delete(note)
    db.session.commit()
    return redirect(f'/contracts/{salesorder_id}#notes')



# Dashboard

@app.route('/dashboard')
@login_required
def dashboard():
    orders = Contract.query.order_by(Contract.date.desc()).all()

    total = sum((o.cf_item_contract_price or 0) for o in orders)

    by_month = {}
    by_office = {}
    for o in orders:
        month = o.date[:7] if o.date else 'Unknown'
        office = o.location_name or 'Unknown'

        by_month.setdefault(month, {'count': 0, 'total': 0})
        by_month[month]['count'] += 1
        by_month[month]['total'] += o.cf_item_contract_price or 0

        by_office.setdefault(office, {'count': 0, 'total': 0})
        by_office[office]['count'] += 1
        by_office[office]['total'] += o.cf_item_contract_price or 0

    by_month = dict(sorted(by_month.items(), reverse=True))
    by_office = dict(sorted(by_office.items()))

    return render_template('dashboard.html', contracts=orders, total=total, by_month=by_month, by_office=by_office)


# Functions

def _build_contract_data(salesorder_id):
    """Shared data-assembly for PDF and DOCX contract downloads."""
    contract = zoho.get_sales_order(salesorder_id)
    form_data = zoho.contract_to_form_data(contract)
    customers = {c.customer_id: c.customer_name for c in Customer.query.all()}
    items = {i.item_id: i for i in Item.query.all()}

    commodity_item = items.get(form_data.get('commodity', ''))
    origin = commodity_item.origin if commodity_item and commodity_item.origin else ''

    return contract, {
        'date': contract.get('date', ''),
        'contract_number': contract.get('salesorder_number', ''),
        'seller': customers.get(form_data['seller'], ''),
        'buyer': customers.get(form_data['buyer'], ''),
        'quantity': form_data['quantity'],
        'uom': form_data['uom'],
        'shipment': form_data['shipping_date'],
        'price': form_data['commodity_rate'],
        'other_conditions': form_data['delivery_notes'],
        'broker': contract.get('salesperson_name', ''),
        'origin': origin,
        'quality': '', 'grades': '', 'weights': '', 'governing_contract': '',
        'discount': '', 'moisture': '', 'damage': '', 'heat_damage': '',
        'foreign_materials': '', 'splits': '', 'payment': '', 'demurrage': '',
    }


def first_time_startup():
    wipe_tasks()
    seed_tasks()
    sync_items()
    sync_customers()
    sync_employees()
    create_user()


@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.role, User.display_name).all()
    return render_template('admin_users.html', users=users)


@app.route('/admin/users/create', methods=['POST'])
@login_required
@admin_required
def admin_create_user():
    email = request.form.get('email', '').strip().lower()
    display_name = request.form.get('display_name', '').strip()
    role = request.form.get('role', 'broker')
    if not email:
        flash('Email is required.', 'danger')
        return redirect('/admin/users')
    if User.query.filter_by(email=email).first():
        flash(f'{email} already exists.', 'warning')
        return redirect('/admin/users')
    db.session.add(User(email=email, display_name=display_name, role=role))
    db.session.commit()
    flash(f'User {email} added.', 'success')
    return redirect('/admin/users')


@app.route('/admin/users/<int:user_id>/role', methods=['POST'])
@login_required
@admin_required
def admin_update_user_role(user_id):
    user = User.query.get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect('/admin/users')
    new_role = request.form.get('role')
    if new_role not in ('admin', 'broker'):
        flash('Invalid role.', 'danger')
        return redirect('/admin/users')
    user.role = new_role
    db.session.commit()
    flash(f'{user.email} role updated to {new_role}.', 'success')
    return redirect('/admin/users')


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = User.query.get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect('/admin/users')
    if user.id == current_user.id:
        flash('Cannot delete your own account.', 'danger')
        return redirect('/admin/users')
    db.session.delete(user)
    db.session.commit()
    flash(f'{user.email} removed.', 'success')
    return redirect('/admin/users')


def create_user():
    seed_users = [
        ('rye@mcdonaldpelz.com', 'Rye Pankoski', 'admin'),
        ('julia@mcdonaldpelz.com', 'Julia', 'admin'),
        ('enrique@mcdonaldpelz.com', 'Enrique', 'broker'),
    ]
    for email, display_name, role in seed_users:
        if not User.query.filter_by(email=email).first():
            db.session.add(User(email=email, display_name=display_name, role=role))
    db.session.commit()
    return 'Users seeded.'


def wipe_tasks():
    Task.query.delete()
    db.session.commit()
    return "All tasks wiped."


def wipe_audit():
    AuditLog.query.delete()
    db.session.commit()
    return 'All audit logs wiped.'


def wipe_users():
    User.query.delete()
    db.session.commit()
    return 'All users wiped.'


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0')