from core.models import Task, TaskTemplate, db

def check_task_reactivity(salesorder_id, changed_fields):
    """
    Reopen completed tasks if their tracked field value has changed.
    changed_fields: dict of {field_name: new_value}
    """
    tasks = Task.query.filter_by(books_sales_order_id=salesorder_id).all()
    for task in tasks:
        if task.status == 'complete' and task.template.books_field:
            new_value = changed_fields.get(task.template.books_field)
            if new_value is not None and str(new_value) != str(task.completed_value):
                task.status = 'pending'
    db.session.commit()

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