import sqlite3

db = sqlite3.connect('neri.db')
db.row_factory = sqlite3.Row

# Get all tasks for user 1 and check categories
tasks = db.execute("SELECT id, title, category FROM profession_tasks WHERE user_id=1").fetchall()

print(f"Total tasks found: {len(tasks)}")
career_count = 0
core_count = 0

for t in tasks:
    if t['category'] == 'career':
        career_count += 1
    elif t['category'] == 'core':
        core_count += 1
        
print(f"Core: {core_count}, Career: {career_count}")

db.close()
