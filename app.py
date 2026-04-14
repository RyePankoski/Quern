from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from core.zoho import get_sales_orders, sync_employees, sync_items, sync_customers
from flask import Flask, render_template, request, redirect, flash, send_file
from core.models import db, Customer, Item, Employee, Task, TaskTemplate, User, AuditLog, ContractMeta, Shipment, \
    BrokerCommission
from core.tasks import generate_tasks, check_task_reactivity
from core.pdf import generate_contract_pdf
from datetime import datetime
from core import zoho
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///quern.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.getenv("SECRET_KEY")
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


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

    orders = get_sales_orders()
    customer_map = {c.customer_id: c.customer_name for c in Customer.query.all()}

    contracts = []
    for order in orders:
        buyer_id = order.get('cf_buyer', '')
        order['cf_buyer'] = customer_map.get(buyer_id, buyer_id)
        line_items = order.get('line_items', [])
        if any(li.get('item_id') == item_id for li in line_items):
            contracts.append(order)

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

    # Fetch all contracts and filter by buyer or seller
    orders = get_sales_orders()
    customer_map = {c.customer_id: c.customer_name for c in Customer.query.all()}

    contracts = []
    for order in orders:
        buyer_id = order.get('cf_buyer', '')
        order['cf_buyer'] = customer_map.get(buyer_id, buyer_id)
        if order.get('customer_id') == customer_id or buyer_id == customer_id:
            contracts.append(order)

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


@app.route('/employees')
@login_required
def employees_view():
    employees = Employee.query.order_by(Employee.employee_name).all()
    return render_template('employees.html', employees=employees)


@app.route('/new_contract')
@login_required
def new_contract():
    items = Item.query.all()
    customers = Customer.query.all()
    employees = Employee.query.all()
    locations = zoho.get_locations()
    prefill = None
    duplicate_id = request.args.get('duplicate')
    if duplicate_id:
        raw = zoho.get_sales_order(duplicate_id)
        prefill = zoho.contract_to_form_data(raw)
    return render_template('new_contract.html', items=items, customers=customers, employees=employees, prefill=prefill,
                           locations=locations)


@app.route('/bulk_edit')
@login_required
def bulk_edit():
    orders = get_sales_orders()
    customers = {c.customer_id: c.customer_name for c in Customer.query.all()}
    for contract in orders:
        buyer_id = contract.get('cf_buyer', '')
        contract['cf_buyer'] = customers.get(buyer_id, buyer_id)
    return render_template('bulk_edit.html', contracts=orders)


@app.route('/contracts')
@login_required
def contracts():
    page = request.args.get('page', 1, type=int)
    orders = get_sales_orders(page=page)
    customers = {c.customer_id: c.customer_name for c in Customer.query.all()}
    for contract in orders:
        buyer_id = contract.get('cf_buyer', '')
        contract['cf_buyer'] = customers.get(buyer_id, buyer_id)
    return render_template('contracts.html', contracts=orders, page=page)


@app.route('/contracts/<salesorder_id>')
@login_required
def contract_detail(salesorder_id):
    contract = zoho.get_sales_order(salesorder_id)

    custom_fields = {f['api_name']: f['value'] for f in contract.get('custom_fields', [])}
    contract['custom'] = custom_fields

    customers = Customer.query.all()
    customer_map = {c.customer_id: c.customer_name for c in customers}

    buyer_id = contract['custom'].get('cf_buyer', '')
    contract['custom']['cf_buyer'] = customer_map.get(buyer_id, buyer_id)

    items = Item.query.all()

    tasks = Task.query.filter_by(
        books_sales_order_id=salesorder_id
    ).join(TaskTemplate).order_by(TaskTemplate.order).all()

    meta = ContractMeta.query.filter_by(books_sales_order_id=salesorder_id).first()
    shipments = Shipment.query.filter_by(books_sales_order_id=salesorder_id).all()
    commissions = BrokerCommission.query.filter_by(books_sales_order_id=salesorder_id).all()
    employees = Employee.query.all()
    employee_map = {e.employee_id: e.employee_name for e in employees}

    # Find the employee record matching the contract's salesperson
    salesperson_zoho_id = contract.get('salesperson_id', '')
    salesperson_employee = next(
        (e for e in employees if e.salesperson_id == salesperson_zoho_id), None
    )

    return render_template('contract_detail.html',
                           contract=contract, customers=customers, items=items,
                           tasks=tasks, meta=meta, shipments=shipments,
                           commissions=commissions, employee_map=employee_map,
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

    orders = get_sales_orders()
    contract_map = {o['salesorder_id']: o for o in orders}

    task_list = []
    for row in task_counts:
        contract = contract_map.get(row.books_sales_order_id, {})
        task_list.append({
            'salesorder_id': row.books_sales_order_id,
            'salesorder_number': contract.get('salesorder_number', row.books_sales_order_id),
            'location_name': contract.get('location_name', ''),
            'total': row.total,
            'pending': row.pending
        })

    task_list.sort(key=lambda x: x['pending'], reverse=True)
    return render_template('tasks.html', task_list=task_list)


@app.route('/admin/audit')
@login_required
def audit_log_view():
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(200).all()
    return render_template('admin_audit.html', logs=logs)


# Submission/Api Call

@app.route('/submit_contract', methods=['POST'])
@login_required
def submit_contract_route():
    # Build a mutable copy of form data so we can resolve IDs to names
    form_data = request.form.to_dict(flat=True)

    # S4: resolve buyer ID → name for Books custom field
    buyer_id = form_data.get('buyer', '')
    buyer = Customer.query.get(buyer_id)
    form_data['buyer_name'] = buyer.customer_name if buyer else ''

    # S5: first broker → salesperson, second broker → cf_co_broker
    broker_employees = request.form.getlist('broker_employee[]')
    form_data['salesperson_employee_id'] = broker_employees[0] if len(broker_employees) > 0 else ''
    form_data['second_broker_employee_id'] = broker_employees[1] if len(broker_employees) > 1 else ''

    result = zoho.submit_contract(form_data)
    if result.get('code', 0) == 0:
        salesorder_id = result['salesorder']['salesorder_id']
        salesorder_number = result['salesorder']['salesorder_number']
        office = request.form.get('location_name', 'Head Office')
        generate_tasks(salesorder_id, country=office)

        # Save local meta
        in_network_val = request.form.get('in_network')
        meta = ContractMeta(
            books_sales_order_id=salesorder_id,
            in_network=True if in_network_val == 'true' else False if in_network_val == 'false' else None
        )
        db.session.add(meta)

        # Save shipments
        booking_numbers = request.form.getlist('booking_number[]')
        shipment_quantities = request.form.getlist('shipment_quantity[]')
        for booking, qty in zip(booking_numbers, shipment_quantities):
            if booking or qty:
                db.session.add(Shipment(
                    books_sales_order_id=salesorder_id,
                    booking_number=booking,
                    quantity=float(qty) if qty else None
                ))
        db.session.commit()

        # Save broker splits and stuff

        # Save broker commissions
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
            user=current_user.username,
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

    allowed_fields = {'vessel_name', 'quantity', 'seller_reference', 'shipping_date_end', 'uom', 'transportation', 'co_broker_name'}
    if field not in allowed_fields:
        return {'ok': False, 'error': 'Invalid field'}, 400

    contract = zoho.get_sales_order(salesorder_id)
    form_data = zoho.contract_to_form_data(contract)
    form_data[field] = value

    result = zoho.update_contract(salesorder_id, form_data)
    if result.get('code', 0) == 0:
        check_task_reactivity(salesorder_id, {field: value})
        return {'ok': True}
    else:
        return {'ok': False, 'error': result.get('message', 'Unknown error')}, 500


@app.route('/contracts/<salesorder_id>/update', methods=['POST'])
@login_required
def update_contract(salesorder_id):
    # Build mutable form data with resolved IDs
    form_data = request.form.to_dict(flat=True)

    # S4: resolve buyer ID → name
    buyer_id = form_data.get('buyer', '')
    buyer = Customer.query.get(buyer_id)
    form_data['buyer_name'] = buyer.customer_name if buyer else ''

    # S5: first broker → salesperson, second → cf_co_broker
    broker_employees = request.form.getlist('broker_employee[]')
    form_data['salesperson_employee_id'] = broker_employees[0] if len(broker_employees) > 0 else ''
    form_data['second_broker_employee_id'] = broker_employees[1] if len(broker_employees) > 1 else ''

    result = zoho.update_contract(salesorder_id, form_data)
    if result.get('code', 0) == 0:
        check_task_reactivity(salesorder_id, form_data)

        # Save local meta
        meta = ContractMeta.query.filter_by(books_sales_order_id=salesorder_id).first()
        if not meta:
            meta = ContractMeta(books_sales_order_id=salesorder_id)
            db.session.add(meta)
        in_network_val = request.form.get('in_network')
        meta.in_network = True if in_network_val == 'true' else False if in_network_val == 'false' else None

        # Replace shipments
        Shipment.query.filter_by(books_sales_order_id=salesorder_id).delete()
        booking_numbers = request.form.getlist('booking_number[]')
        shipment_quantities = request.form.getlist('shipment_quantity[]')
        for booking, qty in zip(booking_numbers, shipment_quantities):
            if booking or qty:
                db.session.add(Shipment(
                    books_sales_order_id=salesorder_id,
                    booking_number=booking,
                    quantity=float(qty) if qty else None
                ))
        db.session.commit()

        # Replace broker commisions/split
        # Replace broker commissions
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


@app.route('/contracts/<salesorder_id>/pdf')
@login_required
def contract_pdf(salesorder_id):
    contract = zoho.get_sales_order(salesorder_id)
    form_data = zoho.contract_to_form_data(contract)
    customers = {c.customer_id: c.customer_name for c in Customer.query.all()}
    logo_path = os.path.join(app.root_path, 'static', 'img', 'logo_header.jpeg')

    data = {
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
        'quality': '', 'grades': '', 'weights': '', 'governing_contract': '',
        'discount': '', 'moisture': '', 'damage': '', 'heat_damage': '',
        'foreign_materials': '', 'splits': '', 'payment': '', 'demurrage': '',
    }

    buffer = generate_contract_pdf(data, logo_path)
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"{contract.get('salesorder_number', 'contract')}.pdf"
    )


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
        user=current_user.username,
        method=request.method,
        path=path,
        salesorder_id=salesorder_id,
        timestamp=datetime.utcnow()
    )
    db.session.add(log)
    db.session.commit()


# User auth and login routes


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect('/')
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')


# Admin task template creation.

@app.route('/admin/templates')
@login_required
def admin_templates():
    templates = TaskTemplate.query.order_by(TaskTemplate.country, TaskTemplate.order).all()
    return render_template('admin_templates.html', templates=templates)


@app.route('/admin/templates/create', methods=['POST'])
@login_required
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
    task.status = 'complete'
    task.completed_value = data.get('completed_value', '')
    task.completed_at = datetime.utcnow()
    db.session.commit()
    return {'ok': True}


# Resource creation, like the contracts JSON


@app.route('/api/contracts')
@login_required
def contracts_json():
    page = request.args.get('page', 1, type=int)
    orders = get_sales_orders(page=page)
    customers = {c.customer_id: c.customer_name for c in Customer.query.all()}
    for contract in orders:
        buyer_id = contract.get('cf_buyer', '')
        contract['cf_buyer'] = customers.get(buyer_id, buyer_id)
    return {'contracts': orders, 'page': page}


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
    meta = ContractMeta.query.filter_by(books_sales_order_id=salesorder_id).first()
    if not meta:
        meta = ContractMeta(books_sales_order_id=salesorder_id)
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
    vessel_names = request.form.getlist('vessel_name[]')
    booking_numbers = request.form.getlist('booking_number[]')
    for vessel, booking in zip(vessel_names, booking_numbers):
        if vessel or booking:
            shipment = Shipment(
                books_sales_order_id=salesorder_id,
                vessel_name=vessel,
                booking_number=booking
            )
            db.session.add(shipment)

    db.session.commit()
    return redirect(request.referrer or f'/contracts/{salesorder_id}')


@app.route('/contracts/<salesorder_id>/shipments/add', methods=['POST'])
@login_required
def add_shipment(salesorder_id):
    data = request.get_json()
    shipment = Shipment(
        books_sales_order_id=salesorder_id,
        vessel_name=data.get('vessel_name', ''),
        booking_number=data.get('booking_number', '')
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


# Dashboard

@app.route('/dashboard')
@login_required
def dashboard():
    orders = get_sales_orders(page=1)

    total = sum(o.get('total', 0) for o in orders)

    by_month = {}
    by_office = {}
    for o in orders:
        month = o.get('date', '')[:7] if o.get('date') else 'Unknown'
        office = o.get('location_name') or 'Unknown'

        by_month.setdefault(month, {'count': 0, 'total': 0})
        by_month[month]['count'] += 1
        by_month[month]['total'] += o.get('total', 0)

        by_office.setdefault(office, {'count': 0, 'total': 0})
        by_office[office]['count'] += 1
        by_office[office]['total'] += o.get('total', 0)

    by_month = dict(sorted(by_month.items(), reverse=True))
    by_office = dict(sorted(by_office.items()))

    return render_template('dashboard.html', contracts=orders, total=total, by_month=by_month, by_office=by_office)


# Functions

def first_time_startup():
    wipe_tasks()
    seed_tasks()
    sync_items()
    sync_customers()
    sync_employees()
    create_user()


def create_user():
    if User.query.first():
        return 'User already exists'
    user = User()
    user.username = 'admin'
    user.set_password('rdp96')
    db.session.add(user)
    db.session.commit()
    return redirect('/logout')


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