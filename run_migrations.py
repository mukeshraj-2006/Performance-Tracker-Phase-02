"""Safe one-time migration runner — run this to add new columns."""
import sqlite3

DB = 'neri.db'
db = sqlite3.connect(DB)

migrations = [
    ("profession_tasks", "category", "TEXT", "core"),
    ("user_profiles",    "date_of_birth", "TEXT", None),
]

for table, col, col_type, default in migrations:
    if default is not None:
        sql = f"ALTER TABLE {table} ADD COLUMN {col} {col_type} DEFAULT '{default}'"
    else:
        sql = f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
    try:
        db.execute(sql)
        db.commit()
        print(f"[ADDED] {table}.{col}")
    except Exception as e:
        print(f"[SKIP]  {table}.{col} — {e}")

# Verify
for table in ('profession_tasks', 'user_profiles'):
    cols = [r[1] for r in db.execute(f'PRAGMA table_info({table})').fetchall()]
    print(f"  {table} columns: {cols}")

db.close()
print("Done.")
