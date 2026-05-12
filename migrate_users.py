"""
One-time migration: replace username/password_hash columns with email/display_name/role.
Run once on the server: python migrate_users.py
Safe to run again — checks for column existence first.
"""
import sqlite3
import os

DB_PATH = os.getenv('DATABASE_URL', 'instance/quern.db').replace('sqlite:///', '')

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Check existing columns
cur.execute("PRAGMA table_info(users)")
cols = {row[1] for row in cur.fetchall()}
print(f"Existing columns: {cols}")

# SQLite doesn't support DROP COLUMN before 3.35, so we do a table rebuild
if 'email' not in cols:
    print("Migrating users table...")
    cur.executescript("""
        BEGIN;
        CREATE TABLE users_new (
            id INTEGER PRIMARY KEY,
            email VARCHAR(200) UNIQUE NOT NULL,
            display_name VARCHAR(200),
            role VARCHAR(50) NOT NULL DEFAULT 'broker'
        );
        DROP TABLE users;
        ALTER TABLE users_new RENAME TO users;
        COMMIT;
    """)
    print("Done. users table rebuilt with email/display_name/role.")
else:
    print("email column already present — no migration needed.")

conn.close()