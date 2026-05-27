from core.models import *



def create_user():
    seed_users = [
        ('rye@mcdonaldpelz.com', 'Rye Pankoski', 'admin'),
        ('julia@mcdonaldpelz.com', 'Julia', 'admin'),
        ('enrique@mcdonaldpelz.com', 'Enrique', 'broker'),
    ]

    print(seed_users[0])
    for email, display_name, role in seed_users:
        if not User.query.filter_by(email=email).first():
            db.session.add(User(email=email, display_name=display_name, role=role)) # noqa
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
