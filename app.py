from flask import Flask, render_template, request, redirect, session, flash
import zoho
from zoho import get_sales_orders, sync_employees, sync_items, sync_customers
from models import db, Customer, Item, Employee, Task, TaskTemplate

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///quern.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.secret_key = '34156243v651243nb12563b41'

db.init_app(app)


@app.route('/')
def home():
    return render_template('home.html')


@app.route('/import_contract', methods=['GET', 'POST'])
def import_contract():
    return render_template('import_contract.html')


@app.route('/new_contract')
def new_contract():
    items = Item.query.all()
    customers = Customer.query.all()
    employees = Employee.query.all()
    return render_template('new_contract.html', items=items, customers=customers, employees=employees)


@app.route('/submit_contract', methods=['POST'])
def submit_contract_route():
    result = zoho.submit_contract(request.form)
    if result.get('code', 0) == 0:
        salesorder_id = result['salesorder']['salesorder_id']
        generate_tasks(salesorder_id)
        flash('Contract submitted successfully.', 'success')
        return redirect('/new_contract')
    else:
        flash(f"Submission failed: {result.get('message', 'Unknown error')}", 'danger')
        return redirect('/new_contract')


@app.route('/contracts')
def contracts():
    orders = get_sales_orders()
    customers = {c.customer_id: c.customer_name for c in Customer.query.all()}
    for contract in orders:
        buyer_id = contract.get('cf_buyer', '')
        contract['cf_buyer'] = customers.get(buyer_id, buyer_id)
    return render_template('contracts.html', contracts=orders)


@app.route('/contracts/<salesorder_id>')
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


@app.route('/contracts/refresh')
def refresh_contracts():
    session.pop('contracts_cache', None)
    return redirect('/contracts')


@app.route('/contracts/<salesorder_id>/update', methods=['POST'])
def update_contract(salesorder_id):
    result = zoho.update_contract(salesorder_id, request.form)
    if result.get('code', 0) == 0:
        tasks = Task.query.filter_by(books_sales_order_id=salesorder_id).all()
        for task in tasks:
            if task.status == 'complete' and task.template.books_field:
                current_value = request.form.get(task.template.books_field, '')
                if str(current_value) != str(task.completed_value):
                    task.status = 'pending'
        db.session.commit()
        flash('Contract updated successfully.', 'update')
    else:
        flash(f"Update failed: {result.get('message', 'Unknown error')}", 'danger')
    return redirect(request.referrer or '/contracts')


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


@app.route('/tasks')
def tasks_view():
    from sqlalchemy import func
    task_counts = db.session.query(
        Task.books_sales_order_id,
        func.count(Task.id).label('total'),
        func.sum(db.case((Task.status == 'pending', 1), else_=0)).label('pending')
    ).group_by(Task.books_sales_order_id).all()

    contract_ids = [t.books_sales_order_id for t in task_counts]
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


def generate_tasks(salesorder_id, country='Boulder'):
    existing = Task.query.filter_by(books_sales_order_id=salesorder_id).first()
    if existing:
        return
    templates = TaskTemplate.query.filter_by(country=country).order_by(TaskTemplate.order).all()
    for template in templates:
        task = Task(
            books_sales_order_id=salesorder_id,
            template_id=template.id,
            assigned_to=None,
            status='pending'
        )
        db.session.add(task)
    db.session.commit()


@app.route('/wipe_tasks')
def wipe_tasks():
    Task.query.delete()
    db.session.commit()
    return "All tasks wiped."


from datetime import datetime


@app.route('/tasks/<int:task_id>/confirm', methods=['POST'])
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


def first_time_startup():
    sync_items()
    sync_customers()
    sync_employees()
    seed_tasks()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # first_time_startup()

    app.run(debug=True, host='0.0.0.0')
