from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from core.zoho import get_sales_orders, sync_employees, sync_items, sync_customers
from flask import Flask, render_template, request, redirect, flash, send_file
from core.models import db, Customer, Item, Employee, Task, TaskTemplate, User, AuditLog
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


@app.route('/counterparties')
@login_required
def counterparties():
    customers = Customer.query.order_by(Customer.customer_name).all()
    return render_template('counterparties.html', customers=customers)


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
    return render_template('new_contract.html', items=items, customers=customers, employees=employees, prefill=prefill, locations=locations)


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

    return render_template('contract_detail.html', contract=contract, customers=customers, items=items, tasks=tasks)


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
    result = zoho.submit_contract(request.form)
    if result.get('code', 0) == 0:
        salesorder_id = result['salesorder']['salesorder_id']
        salesorder_number = result['salesorder']['salesorder_number']
        office = request.form.get('location_name', 'Head Office')
        generate_tasks(salesorder_id, country=office)
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

    allowed_fields = {'vessel_name', 'quantity'}
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
    result = zoho.update_contract(salesorder_id, request.form)
    if result.get('code', 0) == 0:
        check_task_reactivity(salesorder_id, request.form)
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
    user.set_password('changeme')
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


def debug_first_contract():
    orders = get_sales_orders(page=1)
    if not orders:
        return {'error': 'No contracts found'}
    first_id = orders[0]['salesorder_id']
    contract = zoho.get_sales_order(first_id)
    return contract

def debug_locations():
    return {'locations': zoho.get_locations()}


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print(debug_locations())

    app.run(debug=True, host='0.0.0.0')
