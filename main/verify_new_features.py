import os, sqlite3

# --- Check new files ---
files_to_check = [
    'templates/profile_setup.html',
    'templates/profession_dashboard.html',
    'migrate_user_profiles.py',
]
for f in files_to_check:
    status = "OK" if os.path.exists(f) else "MISSING"
    print("[%s] %s" % (status, f))

# --- Check DB tables ---
conn = sqlite3.connect('neri.db')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = sorted(row[0] for row in cur.fetchall())
conn.close()
print("")
print("Tables in neri.db:")
for t in tables:
    print("  -", t)

# --- Check routes in app.py ---
with open('app.py', encoding='utf-8') as f:
    content = f.read()

routes = ['/profile/setup', '/profession/dashboard', '/api/profession/profile']
print("")
print("Route checks in app.py:")
for route in routes:
    status = "OK" if route in content else "MISSING"
    print("  [%s] %s" % (status, route))

funcs = ['_get_user_profile', '_generate_profession_checklist', 'profile_setup', 'profession_dashboard']
print("")
print("Function checks in app.py:")
for fn in funcs:
    status = "OK" if fn in content else "MISSING"
    print("  [%s] %s" % (status, fn))

print("")
print("All checks done.")
