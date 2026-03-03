import os
import sqlite3
import datetime
import json
import random
import hashlib
try:
    import requests as http_requests
except ImportError:
    http_requests = None

from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db, close_connection, init_db

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_key_neri_dark_mode')
app.config['DATABASE'] = 'neri.db'

# Create / migrate DB tables on startup
def run_schema():
    try:
        db = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
        with open('schema.sql', 'r') as f:
            db.executescript(f.read())
        db.commit()
        db.close()
    except Exception as e:
        print(f"Schema note: {e}")

run_schema()

def _safe_migrations():
    """Additive-only column migrations — idempotent, never destructive."""
    try:
        db = sqlite3.connect(app.config['DATABASE'])
        for sql in [
            "ALTER TABLE profession_tasks ADD COLUMN category TEXT DEFAULT 'core'",
            "ALTER TABLE user_profiles ADD COLUMN date_of_birth TEXT",
            "ALTER TABLE user_profiles ADD COLUMN location TEXT",
            "ALTER TABLE user_profiles ADD COLUMN website TEXT",
        ]:
            try:
                db.execute(sql)
                db.commit()
            except Exception:
                pass  # Column already exists — safe to skip
        db.close()
    except Exception as e:
        print(f"Migration note: {e}")

_safe_migrations()


@app.teardown_appcontext
def teardown_app_context(exception):
    close_connection(exception)

@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    return dict(current_user=user)

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ── Quote helper ──────────────────────────────────────────────────────────────
_quote_cache = {'date': None, 'quote': None, 'author': None}

def get_daily_quote():
    today = datetime.date.today().isoformat()
    if _quote_cache['date'] == today and _quote_cache['quote']:
        return _quote_cache

    fallbacks = [
        {"quote": "The secret of getting ahead is getting started.", "author": "Mark Twain"},
        {"quote": "It always seems impossible until it's done.", "author": "Nelson Mandela"},
        {"quote": "Don't watch the clock; do what it does — keep going.", "author": "Sam Levenson"},
        {"quote": "Success is the sum of small efforts repeated day in and day out.", "author": "Robert Collier"},
        {"quote": "The future depends on what you do today.", "author": "Mahatma Gandhi"},
        {"quote": "Discipline is choosing between what you want now and what you want most.", "author": "Augusta F. Kantra"},
        {"quote": "An investment in knowledge pays the best interest.", "author": "Benjamin Franklin"},
    ]
    # Pick a consistent fallback for today so it doesn't change on reload
    day_index = datetime.date.today().toordinal() % len(fallbacks)
    default = fallbacks[day_index]

    if http_requests:
        try:
            res = http_requests.get(
                'https://api.quotable.io/random?tags=motivational,success,technology',
                timeout=3
            )
            if res.status_code == 200:
                data = res.json()
                _quote_cache.update({
                    'date': today,
                    'quote': data.get('content', default['quote']),
                    'author': data.get('author', default['author'])
                })
                return _quote_cache
        except Exception:
            pass

    _quote_cache.update({'date': today, 'quote': default['quote'], 'author': default['author']})
    return _quote_cache

# ── Activity Recalculation Helper ──────────────────────────────────────────
def recalculate_daily_activity(db, uid, date_str):
    """Accurately calculate and store daily completion percentage"""
    # Nutrition Checklist
    nutrition = db.execute('SELECT is_checked FROM nutrition_checklist WHERE user_id=? AND entry_date=?', (uid, date_str)).fetchall()
    
    # Tasks (Manual Physical Tasks)
    tasks = db.execute('SELECT is_completed FROM tasks WHERE user_id=? AND task_date=?', (uid, date_str)).fetchall()
    
    # Reminders
    reminders = db.execute('SELECT is_done FROM reminders WHERE user_id=? AND reminder_date=?', (uid, date_str)).fetchall()
    
    # Physical Goals
    goals = db.execute('SELECT completed_count, total_count FROM physical_goals WHERE user_id=? AND goal_date=?', (uid, date_str)).fetchall()

    # Physical stats
    phys_total = len(nutrition) + len(tasks) + len(reminders) + sum(g['total_count'] for g in goals)
    phys_done = sum(1 for n in nutrition if n['is_checked']) + \
                 sum(1 for t in tasks if t['is_completed']) + \
                 sum(1 for r in reminders if r['is_done']) + \
                 sum(g['completed_count'] for g in goals)
    
    phys_pct = round((phys_done / phys_total * 100) if phys_total else 0)
    
    # Profession stats (filtered by date)
    prof_tasks = db.execute('SELECT is_completed FROM profession_tasks WHERE user_id=? AND task_date=?', (uid, date_str)).fetchall()
    prof_total = len(prof_tasks)
    prof_done = sum(1 for t in prof_tasks if t['is_completed'])
    prof_pct = round((prof_done / prof_total * 100) if prof_total else 0)
    
    points = phys_done + prof_done
    
    existing = db.execute('SELECT id FROM daily_activity WHERE user_id=? AND entry_date=?', (uid, date_str)).fetchone()
    if existing:
        db.execute('''UPDATE daily_activity SET 
                      physical_completion_pct=?, profession_completion_pct=?, 
                      physical_points=?, profession_points=?, total_points=?,
                      physical_total_count=?, profession_total_count=?
                      WHERE id=?''', 
                   (phys_pct, prof_pct, phys_done, prof_done, points, phys_total, prof_total, existing['id']))
    else:
        db.execute('''INSERT INTO daily_activity 
                      (user_id, entry_date, physical_completion_pct, profession_completion_pct, 
                       physical_points, profession_points, total_points, 
                       physical_total_count, profession_total_count) 
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (uid, date_str, phys_pct, prof_pct, phys_done, prof_done, points, phys_total, prof_total))
    db.commit()
    return {
        'phys_pct': phys_pct, 'prof_pct': prof_pct, 
        'phys_done': phys_done, 'phys_total': phys_total,
        'prof_done': prof_done, 'prof_total': prof_total,
        'combined': round((phys_pct + prof_pct) / 2)
    }
def compute_nutrition_targets(height_cm, weight_kg):
    if not height_cm or not weight_kg or float(weight_kg) <= 0 or float(height_cm) <= 0:
        return None
    h, w = float(height_cm), float(weight_kg)
    bmi = w / ((h / 100) ** 2)
    return {
        'bmi': round(bmi, 1),
        'protein_g': round(w * 1.6),
        'fiber_g': 30 if w >= 70 else 25,
        'water_l': round(w * 0.035, 1),
    }

# ── Nutrition Food Pools ─────────────────────────────────────────────────────
FOOD_POOLS = {
    'breakfast_protein': [
        'eggs', 'Greek yogurt', 'paneer', 'protein smoothie', 'tofu scramble', 
        'cottage cheese', 'moong dal chilla', 'sprouted moong'
    ],
    'lunch_protein': [
        'chicken breast', 'dal (lentils)', 'tofu', 'tempeh', 'legumes (chickpeas, kidney beans)', 
        'soy chunks', 'grilled fish', 'lean beef'
    ],
    'dinner_protein': [
        'fish (salmon, tuna)', 'beans', 'cottage cheese', 'quinoa', 'turkey', 
        'mushrooms with peas', 'edamame', 'lentil soup'
    ],
    'vegetables': [
        'broccoli', 'spinach', 'carrots', 'cauliflower', 'bell peppers', 
        'brussels sprouts', 'sweet potatoes', 'kale', 'green beans'
    ],
    'grains': [
        'oats', 'brown rice', 'roti (whole wheat)', 'quinoa', 'barley', 
        'buckwheat', 'millet', 'whole grain bread'
    ],
    'fruits': [
        'apple', 'guava', 'banana', 'pear', 'orange', 'berries', 'papaya', 'pomegranate'
    ]
}

WORKOUT_ROUTINES = [
    'Cardio & Core: 30 mins running/cycling + plank & crunches',
    'Leg Day: Squats, Lunges, Calf raises, Glute bridges',
    'Chest & Triceps: Push-ups, Dips, Tricep extensions',
    'Back & Biceps: Pull-ups, Rows, Bicep curls',
    'Full Body HIIT: Burpees, Jumping jacks, Mountain climbers',
    'Active Recovery: 45 mins brisk walking or yoga stretch'
]

def build_nutrition_checklist(targets, seed_date=None):
    # Use seed_date (ISO format string) to create a deterministic but changing seed
    if seed_date:
        seed_hash = int(hashlib.md5(seed_date.encode()).hexdigest(), 16)
        rng = random.Random(seed_hash)
    else:
        rng = random.Random()
        
    checklist = []
    
    # ── 1. Calculate rotating workout schedule ─────────────────────────────
    if seed_date:
        try:
            day_idx = datetime.date.fromisoformat(seed_date).toordinal()
        except Exception:
            day_idx = rng.randint(0, 1000)
    else:
        day_idx = rng.randint(0, 1000)
        
    wo = WORKOUT_ROUTINES[day_idx % len(WORKOUT_ROUTINES)]
    
    checklist.extend([
        {'label': 'Warm-up: 5-10 mins dynamic stretching', 'type': 'workout'},
        {'label': wo, 'type': 'workout'},
        {'label': 'Cool-down: 5 mins static stretching', 'type': 'workout'},
        {'label': 'Log your completion and effort', 'type': 'workout'}
    ])

    if not targets:
        return checklist

    # ── 2. Calculate Nutrition Targets ─────────────────────────────────────
    p, f, w = targets['protein_g'], targets['fiber_g'], targets['water_l']
    per_meal = round(p / 3)
    
    # Randomly pick items from pools
    bp = rng.choice(FOOD_POOLS['breakfast_protein'])
    lp = rng.choice(FOOD_POOLS['lunch_protein'])
    dp = rng.choice(FOOD_POOLS['dinner_protein'])
    
    # Pick 2 different vegetables
    veg_pool = FOOD_POOLS['vegetables'][:]
    v1 = rng.choice(veg_pool)
    veg_pool.remove(v1)
    v2 = rng.choice(veg_pool)
    
    gr = rng.choice(FOOD_POOLS['grains'])
    fr = rng.choice(FOOD_POOLS['fruits'])

    checklist.extend([
        {'label': f'Breakfast protein (~{per_meal}g) — {bp}', 'type': 'protein'},
        {'label': f'Lunch protein (~{per_meal}g) — {lp}', 'type': 'protein'},
        {'label': f'Dinner protein (~{per_meal}g) — {dp}', 'type': 'protein'},
        {'label': f'Daily protein target: {p}g total', 'type': 'protein'},
        {'label': f'Vegetable servings ({v1}, {v2}) — towards {f}g fiber goal', 'type': 'fiber'},
        {'label': f'Whole grains for at least one meal — {gr}', 'type': 'fiber'},
        {'label': f'One serving of fruit — {fr}', 'type': 'fiber'},
        {'label': f'Daily fiber target: {f}g total', 'type': 'fiber'},
        {'label': 'Morning: 500ml within 30 min of waking', 'type': 'water'},
        {'label': 'Pre-lunch: 300ml before your meal', 'type': 'water'},
        {'label': 'Afternoon: 500ml between 2–4 PM', 'type': 'water'},
        {'label': 'Evening: 300ml post-workout or with snack', 'type': 'water'},
        {'label': f'Daily water target: {w}L (based on your weight)', 'type': 'water'},
    ])
    
    return checklist

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('overview'))
    return redirect(url_for('login'))

@app.route('/auth/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            return redirect(url_for('overview'))
        flash('Invalid credentials. Please check your username and password.', 'error')
    return render_template('auth.html', mode='signin')

@app.route('/auth/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        try:
            hashed = generate_password_hash(password)
            cur = db.cursor()
            cur.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', 
                        (username, hashed))
            user_id = cur.lastrowid
            cur.execute('INSERT INTO profession_stats (user_id) VALUES (?)', (user_id,))
            db.commit()
            session['user_id'] = user_id
            flash('Account created. Complete your health profile in the Physical section to unlock nutrition insights.', 'success')
            return redirect(url_for('overview'))
        except sqlite3.IntegrityError:
            flash('Username already taken. Please choose a different one.', 'error')
    return render_template('auth.html', mode='signup')

@app.route('/auth/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── Overview — summary dashboard ──────────────────────────────────────────────
@app.route('/overview')
@login_required
def overview():
    db = get_db()
    uid = session['user_id']
    today = datetime.date.today().isoformat()

    # Flash message for today's goals and reminders (once per day/session)
    if not session.get('daily_alert_shown'):
        goals = db.execute('SELECT goal_title FROM physical_goals WHERE user_id = ? AND goal_date = ?', (uid, today)).fetchall()
        rems = db.execute('SELECT title FROM reminders WHERE user_id = ? AND reminder_date = ?', (uid, today)).fetchall()
        
        if goals or rems:
            msg = "Today's Focus: "
            if goals:
                msg += "Goals: " + ", ".join([g['goal_title'] for g in goals]) + ". "
            if rems:
                msg += "Reminders: " + ", ".join([r['title'] for r in rems])
            flash(msg, 'info')
        session['daily_alert_shown'] = True

    # Use the centralized recalculation for today to ensure consistency
    stats = recalculate_daily_activity(db, uid, today)

    # Today's Reminders (Focus for overview sidebar)
    reminders = db.execute(
        'SELECT * FROM reminders WHERE user_id = ? AND (reminder_date = ? OR reminder_date IS NULL) ORDER BY is_done ASC, created_at DESC', 
        (uid, today)
    ).fetchall()

    quote = get_daily_quote()
    now_hour = datetime.datetime.now().hour
    return render_template('overview.html',
        today=today,
        now_hour=now_hour,
        tasks_total=stats['phys_total'],
        tasks_done=stats['phys_done'],
        physical_pct=stats['phys_pct'],
        prof_total=stats['prof_total'], 
        prof_done=stats['prof_done'], 
        profession_pct=stats['prof_pct'],
        combined_score=stats['combined'],
        reminders=reminders,
        quote=quote,
    )

# ── Profession — notebook page ────────────────────────────────────────────────
@app.route('/profession')
@login_required
def profession():
    db = get_db()
    uid = session['user_id']
    today = datetime.date.today().isoformat()
    
    # Get all tasks for this user
    all_prof_tasks = db.execute(
        'SELECT * FROM profession_tasks WHERE user_id = ? ORDER BY is_completed ASC, created_at DESC', (uid,)
    ).fetchall()
    
    # Split into today's tasks and past incomplete tasks
    today_tasks = [t for t in all_prof_tasks if t['task_date'] == today]
    past_pending = [t for t in all_prof_tasks if t['task_date'] < today and not t['is_completed']]
    
    prof_stats = db.execute('SELECT * FROM profession_stats WHERE user_id = ?', (uid,)).fetchone()
    
    # Check if they have a profile; if so, generate the daily career goals
    # The _sync_career_goals function ensures this only adds them on the FIRST visit each day for this user
    profile = _get_user_profile(db, uid)
    if profile:
        _sync_career_goals(db, uid, profile, today)
        
        # After potentially syncing, refresh the tasks list
        all_prof_tasks = db.execute(
            'SELECT * FROM profession_tasks WHERE user_id = ? ORDER BY is_completed ASC, created_at DESC', (uid,)
        ).fetchall()
        # Updates
        today_tasks = [t for t in all_prof_tasks if t['task_date'] == today]
        past_pending = [t for t in all_prof_tasks if t['task_date'] < today and not t['is_completed']]
    
    return render_template('profession.html', 
                           today_tasks=today_tasks, 
                           past_pending=past_pending, 
                           prof_stats=prof_stats, 
                           profile=profile,
                           today=today)

# ── Physical page ─────────────────────────────────────────────────────────────
@app.route('/physical')
@login_required
def physical():
    db = get_db()
    uid = session['user_id']
    today = datetime.date.today().isoformat()
    user = db.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()

    daily = db.execute(
        'SELECT * FROM daily_physical WHERE user_id = ? AND entry_date = ?', (uid, today)
    ).fetchone()
    if not daily:
        db.execute('INSERT INTO daily_physical (user_id, entry_date) VALUES (?, ?)', (uid, today))
        db.commit()
        daily = db.execute(
            'SELECT * FROM daily_physical WHERE user_id = ? AND entry_date = ?', (uid, today)
        ).fetchone()

    targets  = compute_nutrition_targets(user['height'], user['weight'])
    checklist = db.execute(
        'SELECT * FROM nutrition_checklist WHERE user_id = ? AND entry_date = ?', (uid, today)
    ).fetchall()

    if not checklist:
        for item in build_nutrition_checklist(targets, today):
            db.execute(
                'INSERT INTO nutrition_checklist (user_id, entry_date, item_label, item_type) VALUES (?,?,?,?)',
                (uid, today, item['label'], item['type'])
            )
        db.commit()
        checklist = db.execute(
            'SELECT * FROM nutrition_checklist WHERE user_id = ? AND entry_date = ?', (uid, today)
        ).fetchall()
    elif checklist:
        # Backfill: If an old checklist exists without workouts, append them
        has_workouts = any(item['item_type'] == 'workout' for item in checklist)
        if not has_workouts:
            new_items = build_nutrition_checklist(targets, today)
            workout_items = [i for i in new_items if i['type'] == 'workout']
            for item in workout_items:
                db.execute(
                    'INSERT INTO nutrition_checklist (user_id, entry_date, item_label, item_type) VALUES (?,?,?,?)',
                    (uid, today, item['label'], item['type'])
                )
            db.commit()
            checklist = db.execute(
                'SELECT * FROM nutrition_checklist WHERE user_id = ? AND entry_date = ?', (uid, today)
            ).fetchall()

    return render_template('physical.html', daily=daily, targets=targets, checklist=checklist, user=user)

# ── Calendar Tasks API ────────────────────────────────────────────────────────
@app.route('/api/task/add', methods=['POST'])
@login_required
def add_task():
    data = request.json
    db = get_db()
    db.execute('INSERT INTO tasks (user_id, title, task_date) VALUES (?, ?, ?)',
               (session['user_id'], data['title'], data['date']))
    db.commit()
    recalculate_daily_activity(db, session['user_id'], data['date'])
    return jsonify({'status': 'success'})

@app.route('/api/task/toggle', methods=['POST'])
@login_required
def toggle_task():
    data = request.json
    db = get_db()
    uid = session['user_id']
    db.execute('UPDATE tasks SET is_completed = ? WHERE id = ? AND user_id = ?',
               (data['completed'], data['id'], uid))
    db.commit()
    
    task = db.execute('SELECT task_date FROM tasks WHERE id = ? AND user_id = ?', (data['id'], uid)).fetchone()
    if task:
        recalculate_daily_activity(db, uid, task['task_date'])
    return jsonify({'status': 'success'})

@app.route('/api/physical-goals/toggle', methods=['POST'])
@login_required
def toggle_physical_goal():
    data = request.json
    db = get_db()
    uid = session['user_id']
    goal_id = data.get('id')
    completed = 1 if data.get('completed') else 0
    
    goal = db.execute('SELECT goal_date FROM physical_goals WHERE id=? AND user_id=?', (goal_id, uid)).fetchone()
    if not goal:
        return jsonify({'status': 'error', 'message': 'Goal not found'}), 404
        
    db.execute('UPDATE physical_goals SET completed_count=? WHERE id=? AND user_id=?', (completed, goal_id, uid))
    db.commit()
    
    stats = recalculate_daily_activity(db, uid, goal['goal_date'])
    return jsonify({'status': 'success'})

@app.route('/api/physical-goals/add', methods=['POST'])
@login_required
def add_physical_goal():
    data = request.json
    db = get_db()
    uid = session['user_id']
    db.execute('INSERT INTO physical_goals (user_id, goal_title, goal_date) VALUES (?, ?, ?)',
               (uid, data['goal_title'], data['goal_date']))
    db.commit()
    recalculate_daily_activity(db, uid, data['goal_date'])
    return jsonify({'status': 'success'})

@app.route('/api/physical-goals/delete', methods=['POST'])
@login_required
def delete_physical_goal():
    data = request.json
    db = get_db()
    uid = session['user_id']
    goal = db.execute('SELECT goal_date FROM physical_goals WHERE id=? AND user_id=?', (data['id'], uid)).fetchone()
    if goal:
        db.execute('DELETE FROM physical_goals WHERE id=? AND user_id=?', (data['id'], uid))
        db.commit()
        recalculate_daily_activity(db, uid, goal['goal_date'])
    return jsonify({'status': 'success'})


@app.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    date = request.args.get('date')
    db = get_db()
    tasks = db.execute(
        'SELECT * FROM tasks WHERE user_id = ? AND task_date = ?', (session['user_id'], date)
    ).fetchall()
    return jsonify([{
        'id': t['id'], 'title': t['title'],
        'is_completed': bool(t['is_completed']), 'task_date': t['task_date']
    } for t in tasks])

# ── Profession Tasks API ──────────────────────────────────────────────────────
@app.route('/api/profession/tasks', methods=['GET'])
@login_required
def get_profession_tasks():
    db = get_db()
    tasks = db.execute(
        'SELECT * FROM profession_tasks WHERE user_id = ? ORDER BY is_completed ASC, created_at DESC',
        (session['user_id'],)
    ).fetchall()
    return jsonify([{
        'id': t['id'], 'title': t['title'],
        'is_completed': bool(t['is_completed']), 'created_at': t['created_at']
    } for t in tasks])

@app.route('/api/profession/tasks/add', methods=['POST'])
@login_required
def add_profession_task():
    data = request.json
    title = (data.get('title') or '').strip()
    task_date = data.get('date') or datetime.date.today().isoformat()
    category = (data.get('category') or 'core').strip()  # 'core' or 'career'
    if not title:
        return jsonify({'status': 'error'}), 400
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            'INSERT INTO profession_tasks (user_id, title, task_date, category) VALUES (?, ?, ?, ?)',
            (session['user_id'], title, task_date, category)
        )
    except Exception:
        # Fallback if category column not yet migrated
        cur.execute(
            'INSERT INTO profession_tasks (user_id, title, task_date) VALUES (?, ?, ?)',
            (session['user_id'], title, task_date)
        )
    db.commit()
    recalculate_daily_activity(db, session['user_id'], task_date)
    return jsonify({'status': 'success', 'id': cur.lastrowid, 'category': category})

@app.route('/api/profession/tasks/toggle', methods=['POST'])
@login_required
def toggle_profession_task():
    data = request.json
    db = get_db()
    db.execute('UPDATE profession_tasks SET is_completed = ? WHERE id = ? AND user_id = ?',
               (data['completed'], data['id'], session['user_id']))
    db.commit()
    
    # Get task date to recalculate
    task = db.execute('SELECT task_date FROM profession_tasks WHERE id=?', (data['id'],)).fetchone()
    if task and task['task_date']:
        recalculate_daily_activity(db, session['user_id'], task['task_date'])
        
    done  = db.execute('SELECT COUNT(*) FROM profession_tasks WHERE user_id=? AND is_completed=1', (session['user_id'],)).fetchone()[0]
    total = db.execute('SELECT COUNT(*) FROM profession_tasks WHERE user_id=?', (session['user_id'],)).fetchone()[0]
    db.execute('UPDATE profession_stats SET completed_count=?, target_count=? WHERE user_id=?',
               (done, total, session['user_id']))
    db.commit()
    return jsonify({'status': 'success', 'done': done, 'total': total,
                    'pct': round(done/total*100) if total else 0})

@app.route('/api/profession/tasks/edit', methods=['POST'])
@login_required
def edit_profession_task():
    data = request.json
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'status': 'error'}), 400
    db = get_db()
    db.execute('UPDATE profession_tasks SET title=? WHERE id=? AND user_id=?',
               (title, data['id'], session['user_id']))
    db.commit()
    return jsonify({'status': 'success'})

@app.route('/api/profession/tasks/delete', methods=['POST'])
@login_required
def delete_profession_task():
    data = request.json
    db = get_db()
    db.execute('DELETE FROM profession_tasks WHERE id=? AND user_id=?',
               (data['id'], session['user_id']))
    db.commit()
    return jsonify({'status': 'success'})

# ── Reminders API ─────────────────────────────────────────────────────────────
@app.route('/api/reminders/add', methods=['POST'])
@login_required
def add_reminder():
    data = request.json
    title = (data.get('title') or '').strip()
    date = data.get('date')
    if not title:
        return jsonify({'status': 'error'}), 400
    db = get_db()
    cur = db.cursor()
    db.execute('INSERT INTO reminders (user_id, title, reminder_date) VALUES (?, ?, ?)', (session['user_id'], title, date))
    db.commit()
    if date:
        recalculate_daily_activity(db, session['user_id'], date)
    return jsonify({'status': 'success', 'id': cur.lastrowid})

@app.route('/api/reminders/toggle', methods=['POST'])
@login_required
def toggle_reminder():
    data = request.json
    db = get_db()
    db.execute('UPDATE reminders SET is_done=? WHERE id=? AND user_id=?',
               (data['done'], data['id'], session['user_id']))
    db.commit()
    
    rem = db.execute('SELECT reminder_date FROM reminders WHERE id=? AND user_id=?', (data['id'], session['user_id'])).fetchone()
    if rem and rem['reminder_date']:
        recalculate_daily_activity(db, session['user_id'], rem['reminder_date'])
        
    return jsonify({'status': 'success'})

@app.route('/api/reminders/delete', methods=['POST'])
@login_required
def delete_reminder():
    data = request.json
    db = get_db()
    uid = session['user_id']
    rem = db.execute('SELECT reminder_date FROM reminders WHERE id=? AND user_id=?', (data['id'], uid)).fetchone()
    if rem:
        db.execute('DELETE FROM reminders WHERE id=? AND user_id=?', (data['id'], uid))
        db.commit()
        if rem['reminder_date']:
            recalculate_daily_activity(db, uid, rem['reminder_date'])
    return jsonify({'status': 'success'})

# ── Physical API ──────────────────────────────────────────────────────────────
@app.route('/api/physical/update', methods=['POST'])
@login_required
def update_physical():
    data = request.json
    db = get_db()
    today = datetime.date.today().isoformat()
    uid = session['user_id']

    if 'water' in data:
        db.execute('UPDATE daily_physical SET water_intake_liters=? WHERE user_id=? AND entry_date=?',
                   (data['water'], uid, today))
    if 'food_log' in data:
        db.execute('UPDATE daily_physical SET food_log=? WHERE user_id=? AND entry_date=?',
                   (data['food_log'], uid, today))
    if 'personal_info' in data:
        info = data['personal_info']
        h, w, bg = info.get('height'), info.get('weight'), info.get('blood_group')
        bmi = None
        if h and w and float(h) > 0 and float(w) > 0:
            bmi = round(float(w) / ((float(h)/100) ** 2), 1)
        db.execute('UPDATE users SET height=?, weight=?, blood_group=?, bmi=? WHERE id=?',
                   (h, w, bg, bmi, uid))
        if h and w:
            db.execute('DELETE FROM nutrition_checklist WHERE user_id=? AND entry_date=?', (uid, today))
    db.commit()
    return jsonify({'status': 'success'})

@app.route('/api/nutrition/checklist/toggle', methods=['POST'])
@login_required
def toggle_nutrition_item():
    data = request.json
    db = get_db()
    uid = session['user_id']
    today = datetime.date.today().isoformat()
    
    db.execute('UPDATE nutrition_checklist SET is_checked=? WHERE id=? AND user_id=?',
               (data['checked'], data['id'], uid))
    db.commit()
    
    stats = recalculate_daily_activity(db, uid, today)
    
    return jsonify({'status': 'success', 'percentage': stats['phys_pct']})

# ── Calendar & Daily Tracking API ────────────────────────────────────────────
@app.route('/api/calendar/month', methods=['GET'])
@login_required
def get_calendar_month():
    """Get all daily activities and reminders for a month"""
    year = request.args.get('year', datetime.date.today().year, type=int)
    month = request.args.get('month', datetime.date.today().month, type=int)
    db = get_db()
    uid = session['user_id']
    
    activities = db.execute(
        'SELECT * FROM daily_activity WHERE user_id = ? AND entry_date LIKE ?',
        (uid, f'{year:04d}-{month:02d}-%')
    ).fetchall()
    
    goals = db.execute(
        'SELECT goal_date, COUNT(*) as count FROM physical_goals WHERE user_id = ? AND goal_date LIKE ? GROUP BY goal_date',
        (uid, f'{year:04d}-{month:02d}-%')
    ).fetchall()
    
    prof_tasks_dates = db.execute(
        'SELECT task_date, COUNT(*) as count FROM profession_tasks WHERE user_id = ? AND task_date LIKE ? GROUP BY task_date',
        (uid, f'{year:04d}-{month:02d}-%')
    ).fetchall()
    
    reminders = db.execute(
        'SELECT reminder_date, COUNT(*) as count FROM reminders WHERE user_id = ? AND reminder_date LIKE ? GROUP BY reminder_date',
        (uid, f'{year:04d}-{month:02d}-%')
    ).fetchall()
    
    activity_map = {}
    
    # Process all dates that have ANYTHING
    all_dates = set([a['entry_date'] for a in activities] + 
                    [g['goal_date'] for g in goals] + 
                    [r['reminder_date'] for r in reminders] +
                    [p['task_date'] for p in prof_tasks_dates if p['task_date']])
    
    today_for_month = datetime.date.today()

    for date_str in all_dates:
        act = next((dict(a) for a in activities if a['entry_date'] == date_str), None)
        has_goals = any(g['goal_date'] == date_str for g in goals)
        has_reminders = any(r['reminder_date'] == date_str for r in reminders)
        
        if not act and (has_goals or has_reminders):
            # Only recalculate if it's today or future; for past, don't create phantom records
            try:
                date_obj = datetime.date.fromisoformat(date_str)
            except Exception:
                date_obj = None
            if date_obj and date_obj >= today_for_month:
                stats = recalculate_daily_activity(db, uid, date_str)
                act = {'physical_completion_pct': stats['phys_pct'], 'profession_completion_pct': stats['prof_pct'], 'total_points': stats['phys_done'] + stats['prof_done']}
            else:
                act = {'physical_completion_pct': 0, 'total_points': 0}
        
        if not act:
            act = {'physical_completion_pct': 0, 'total_points': 0}
            
        activity_map[date_str] = act
        if has_goals: activity_map[date_str]['has_goals'] = True
        if has_reminders: activity_map[date_str]['has_reminders'] = True
        
        # Calculate overall score for the day
        phys_pct = act.get('physical_completion_pct', 0)
        day_prof_pct = act.get('profession_completion_pct', 0)
        activity_map[date_str]['overall_score'] = round((phys_pct + day_prof_pct) / 2)
        
        # Keyword extraction (Prioritize day_note)
        if act and act.get('day_note'):
            activity_map[date_str]['keyword'] = act['day_note'][:15]
        elif has_reminders or has_goals:
            rem_title = db.execute('SELECT title FROM reminders WHERE user_id=? AND reminder_date=?', (uid, date_str)).fetchone()
            goal_title = db.execute('SELECT goal_title FROM physical_goals WHERE user_id=? AND goal_date=?', (uid, date_str)).fetchone()
            keyword = (rem_title['title'] if rem_title else goal_title['goal_title'] if goal_title else "").split()[0][:10]
            activity_map[date_str]['keyword'] = keyword
        
        if act and act.get('day_note'):
            activity_map[date_str]['day_note'] = act['day_note']

    return jsonify(activity_map)

@app.route('/api/activity/note/update', methods=['POST'])
@login_required
def update_day_note():
    """Update the persistent note for a specific date"""
    data = request.json
    date_str = data.get('date')
    note = data.get('note', '').strip()
    if not date_str:
        return jsonify({'status': 'error'}), 400
        
    db = get_db()
    uid = session['user_id']
    
    existing = db.execute('SELECT id FROM daily_activity WHERE user_id=? AND entry_date=?', (uid, date_str)).fetchone()
    if existing:
        db.execute('UPDATE daily_activity SET day_note=? WHERE id=?', (note, existing['id']))
    else:
        db.execute('INSERT INTO daily_activity (user_id, entry_date, day_note) VALUES (?, ?, ?)',
                   (uid, date_str, note))
    db.commit()
    return jsonify({'status': 'success'})

@app.route('/api/calendar/day', methods=['GET'])
@login_required
def get_calendar_day():
    """Get activities and tasks for a specific date"""
    date = request.args.get('date')
    if not date:
        return jsonify({'status': 'error'}), 400
    
    db = get_db()
    uid = session['user_id']
    
    activity = db.execute(
        'SELECT * FROM daily_activity WHERE user_id = ? AND entry_date = ?', (uid, date)
    ).fetchone()
    
    tasks = db.execute(
        'SELECT * FROM tasks WHERE user_id = ? AND task_date = ?', (uid, date)
    ).fetchall()
    
    return jsonify({
        'activity': dict(activity) if activity else None,
        'tasks': [dict(t) for t in tasks]
    })

@app.route('/api/task/update-points', methods=['POST'])
@login_required
def update_task_points():
    """Update daily activity points when task is toggled"""
    data = request.json
    task_date = data.get('task_date')
    db = get_db()
    uid = session['user_id']
    
    # Calculate current completion percentage for the day
    tasks = db.execute(
        'SELECT * FROM tasks WHERE user_id = ? AND task_date = ?', (uid, task_date)
    ).fetchall()
    
    total = len(tasks)
    done = sum(1 for t in tasks if t['is_completed'])
    pct = round((done / total * 100) if total else 0)
    
    # Points: 1 point per completed task
    physical_points = done
    
    # Update or create daily activity record
    existing = db.execute(
        'SELECT * FROM daily_activity WHERE user_id = ? AND entry_date = ?',
        (uid, task_date)
    ).fetchone()
    
    if existing:
        db.execute(
            'UPDATE daily_activity SET physical_completion_pct=?, physical_points=?, total_points=physical_points+profession_points WHERE user_id=? AND entry_date=?',
            (pct, physical_points, uid, task_date)
        )
    else:
        db.execute(
            'INSERT INTO daily_activity (user_id, entry_date, physical_completion_pct, physical_points, total_points) VALUES (?, ?, ?, ?, ?)',
            (uid, task_date, pct, physical_points, physical_points)
        )
    
    db.commit()
    return jsonify({'status': 'success', 'pct': pct, 'points': physical_points})

@app.route('/api/check-edit-allowed', methods=['GET'])
@login_required
def check_edit_allowed():
    """Check if user can edit tasks for a date"""
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'status': 'error'}), 400
    
    target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    today = datetime.date.today()
    
    # Can edit today and future dates, only view past dates
    can_edit = target_date >= today
    can_add = target_date >= today
    
    return jsonify({
        'can_edit': can_edit,
        'can_add': can_add,
        'is_past': target_date < today,
        'is_today': target_date == today,
        'is_future': target_date > today
    })

@app.route('/api/date-view', methods=['GET'])
@login_required
def get_date_view():
    """Get overview, physical, and profession data for a specific date (LIVE version)"""
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'status': 'error'}), 400
    
    db = get_db()
    uid = session['user_id']
    
    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
    
    # Calculate Profession stats live (filtered by date)
    prof_tasks = db.execute('SELECT * FROM profession_tasks WHERE user_id = ? AND task_date = ?', (uid, date_str)).fetchall()
    prof_total = len(prof_tasks)
    prof_done = sum(1 for t in prof_tasks if t['is_completed'])
    prof_pct = round((prof_done / prof_total * 100) if prof_total else 0)
    
    # Calculate Physical stats live
    manual_tasks = db.execute('SELECT * FROM tasks WHERE user_id = ? AND task_date = ?', (uid, date_str)).fetchall()
    checklist = db.execute('SELECT * FROM nutrition_checklist WHERE user_id = ? AND entry_date = ?', (uid, date_str)).fetchall()
    reminders = db.execute('SELECT * FROM reminders WHERE user_id = ? AND reminder_date = ?', (uid, date_str)).fetchall()
    goals = db.execute('SELECT * FROM physical_goals WHERE user_id = ? AND goal_date = ?', (uid, date_str)).fetchall()
    
    phys_total = len(manual_tasks) + len(checklist) + len(reminders) + sum(g['total_count'] for g in goals)
    phys_done = sum(1 for t in manual_tasks if t['is_completed']) + sum(1 for c in checklist if c['is_checked']) + sum(1 for r in reminders if r['is_done']) + sum(g['completed_count'] for g in goals)
    phys_pct = round((phys_done / phys_total * 100) if phys_total else 0)
    
    # Get day note
    act_row = db.execute('SELECT day_note FROM daily_activity WHERE user_id=? AND entry_date=?', (uid, date_str)).fetchone()
    day_note = act_row['day_note'] if act_row else None
    
    combined = round((phys_pct + prof_pct) / 2)

    return jsonify({
        'date': date_str,
        'not_initiated': False,
        'combined': combined,
        'overview': {
            'physical_completion_pct': phys_pct,
            'profession_completion_pct': prof_pct,
            'day_note': day_note
        },
        'physical': {
            'percentage': phys_pct,
            'phys_done': phys_done,
            'phys_total': phys_total,
            'checklist': [dict(c) for c in checklist],
            'goals': [dict(g) for g in goals],
            'reminders': [dict(r) for r in reminders],
            'tasks_list': [dict(t) for t in manual_tasks] 
        },
        'profession': {
            'tasks_total': prof_total,
            'tasks_done': prof_done,
            'percentage': prof_pct,
            'tasks_list': [dict(t) for t in prof_tasks]
        },
        'user': {
            'height': user['height'],
            'weight': user['weight'],
            'blood_group': user['blood_group'],
            'bmi': user['bmi']
        }
    })

# Cleanup complete

@app.route('/api/physical-activities', methods=['GET'])
@login_required
def get_physical_activities():
    """Get list of suggested physical activities"""
    db = get_db()
    activities = db.execute('SELECT * FROM physical_activities ORDER BY activity_category').fetchall()
    return jsonify([dict(a) for a in activities])

@app.route('/api/physical-activities/init', methods=['GET'])
@login_required
def init_physical_activities():
    """Initialize default physical activities if not already present"""
    db = get_db()
    try:
        default_activities = [
            ('Jog', 'Cardio', 'Light jogging', 10),
            ('Cycle', 'Cardio', 'Cycling', 20),
            ('Skipping', 'Cardio', 'Jump rope', 10),
            ('Running', 'Cardio', 'Fast running', 20),
            ('Swimming', 'Cardio', 'Swimming', 30),
            ('Push-ups', 'Strength', 'Upper body strength', 15),
            ('Squats', 'Strength', 'Lower body strength', 15),
            ('Plank', 'Strength', 'Core strength', 10),
            ('Yoga', 'Flexibility', 'Yoga session', 30),
            ('Stretching', 'Flexibility', 'Stretching routine', 15),
            ('Walking', 'Cardio', 'Brisk walking', 30),
            ('Gym Workout', 'Strength', 'Full body gym session', 60),
        ]
        
        for name, category, desc, duration in default_activities:
            try:
                db.execute(
                    'INSERT INTO physical_activities (activity_name, activity_category, description, duration_minutes) VALUES (?, ?, ?, ?)',
                    (name, category, desc, duration)
                )
            except sqlite3.IntegrityError:
                pass  # Already exists
        
        db.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400


@app.route('/api/nutrition-progress/update', methods=['POST'])
@login_required
def update_nutrition_progress():
    """Update nutrition progress for individual items"""
    data = request.json
    entry_date = data.get('entry_date')
    item_id = data.get('item_id')
    progress = data.get('progress', 0)
    
    db = get_db()
    uid = session['user_id']
    
    # Get the item details
    item = db.execute(
        'SELECT * FROM nutrition_checklist WHERE id = ? AND user_id = ? AND entry_date = ?',
        (item_id, uid, entry_date)
    ).fetchone()
    
    if not item:
        return jsonify({'status': 'error'}), 400
    
    # Update or insert progress
    existing = db.execute(
        'SELECT * FROM nutrition_progress WHERE user_id = ? AND entry_date = ? AND item_id = ?',
        (uid, entry_date, item_id)
    ).fetchone()
    
    if existing:
        db.execute(
            'UPDATE nutrition_progress SET progress_percentage = ? WHERE user_id = ? AND entry_date = ? AND item_id = ?',
            (progress, uid, entry_date, item_id)
        )
    else:
        db.execute(
            'INSERT INTO nutrition_progress (user_id, entry_date, item_id, item_label, item_type, progress_percentage) VALUES (?, ?, ?, ?, ?, ?)',
            (uid, entry_date, item_id, item['item_label'], item['item_type'], progress)
        )
    
    db.commit()
    return jsonify({'status': 'success', 'progress': progress})

@app.route('/api/profile/update', methods=['POST'])
@login_required
def update_user_profile():
    """Update user profile from overview page"""
    data = request.json
    height = data.get('height')
    weight = data.get('weight')
    blood_group = data.get('blood_group')
    
    db = get_db()
    uid = session['user_id']
    
    bmi = None
    if height and weight:
        try:
            h = float(height)
            w = float(weight)
            if h > 0 and w > 0:
                bmi = round(w / ((h / 100) ** 2), 1)
        except:
            pass
    
    db.execute(
        'UPDATE users SET height = ?, weight = ?, blood_group = ?, bmi = ? WHERE id = ?',
        (height, weight, blood_group, bmi, uid)
    )
    db.commit()
    
    return jsonify({
        'status': 'success',
        'bmi': bmi,
        'bmi_status': get_bmi_status(bmi) if bmi else None
    })

def get_bmi_status(bmi):
    """Get BMI status: Underweight, Normal, Overweight, Obese"""
    if bmi < 18.5:
        return {'status': 'Underweight', 'color': '#3b82f6', 'recommendation': 'Increase caloric intake'}
    elif bmi < 25:
        return {'status': 'Normal', 'color': '#10b981', 'recommendation': 'Maintain current diet and exercise'}
    elif bmi < 30:
        return {'status': 'Overweight', 'color': '#f59e0b', 'recommendation': 'Reduce caloric intake, increase exercise'}
    else:
        return {'status': 'Obese', 'color': '#ef4444', 'recommendation': 'Consult healthcare provider'}



# ── Profession Personalization System (Isolated / Additive) ──────────────────

def _get_user_profile(db, uid):
    """Safely fetch user profile — returns None if not found (no exception)."""
    try:
        return db.execute(
            'SELECT * FROM user_profiles WHERE user_id = ?', (uid,)
        ).fetchone()
    except Exception:
        return None


def _generate_profession_checklist(profile):
    """
    Generate a personalized daily checklist based on profession type + field.
    Returns a list of task label strings.
    All static — no external API calls, no network dependency.
    """
    if not profile:
        return [
            'Set a learning goal for today',
            'Read one article / chapter',
            'Practice one skill for 30 minutes',
            'Review your progress',
            'Plan tomorrow\'s priorities',
        ]

    ptype = (profile['profession_type'] or '').strip()
    field = (profile['field_of_interest'] or '').strip().lower()

    # --- Student ---
    if ptype == 'Student':
        if 'web' in field or 'frontend' in field or 'ui' in field:
            return [
                'Solve 2 coding problems (LeetCode / HackerRank)',
                'Build 1 small UI component from scratch',
                'Practice 1 CSS layout (Flexbox or Grid)',
                'Review 1 open-source GitHub project',
                'Read 1 technical article or documentation page',
            ]
        elif 'ai' in field or 'ml' in field or 'machine' in field or 'data' in field:
            return [
                'Implement 1 small ML model or algorithm',
                'Study 1 core ML concept (backprop, regularisation, etc.)',
                'Solve 2 data/math problems',
                'Explore 1 public dataset (Kaggle / UCI)',
                'Read 1 research paper abstract or blog post',
            ]
        elif 'mobile' in field or 'android' in field or 'ios' in field or 'flutter' in field:
            return [
                'Build 1 small app screen or widget',
                'Solve 1 coding problem',
                'Read mobile platform documentation',
                'Test app on emulator / device',
                'Code-review your last commit',
            ]
        elif 'cyber' in field or 'security' in field or 'network' in field:
            return [
                'Complete 1 TryHackMe / HackTheBox challenge',
                'Study 1 networking or security concept',
                'Practice 1 command-line exercise',
                'Review 1 CVE or security advisory',
                'Write a short note on what you learned',
            ]
        else:
            # Generic student
            return [
                'Study core subject material for 1 hour',
                'Solve 2 practice problems',
                'Review lecture notes from yesterday',
                'Watch 1 educational video or tutorial',
                'Summarise key takeaways in your notes',
            ]

    # --- Working Professional ---
    elif ptype == 'Working Professional':
        return [
            'Complete 1 priority upskilling task (course / tutorial)',
            'Read 1 industry trend article or newsletter',
            'Identify and improve 1 workflow or process area',
            'Spend 15 mins on professional networking / LinkedIn',
            'Document or share 1 insight with your team',
        ]

    # --- Content Creator ---
    elif ptype == 'Content Creator':
        return [
            'Plan 1 content piece (topic + outline)',
            'Draft or script 1 section of upcoming content',
            'Review last 3 posts\' analytics for insights',
            'Engage meaningfully with 5+ community comments',
            'Research 1 trending topic in your niche',
        ]

    # --- Other / Fallback ---
    else:
        return [
            'Define your top 3 priorities for today',
            'Spend 30 mins on skill development',
            'Review and clear 1 pending task',
            'Reflect on yesterday\'s progress',
            'Plan tomorrow\'s most important action',
        ]


def _generate_career_goals(profile):
    """
    Returns a list of goal title strings based on the user's profile.
    These become persistent profession_tasks with category='career'.
    Separate from _generate_profession_checklist (which is static display-only).
    """
    if not profile:
        return []

    ptype  = (profile['profession_type']     or '').strip()
    field  = (profile['field_of_interest']   or '').lower().strip()
    role   = (profile['role']                or '').lower().strip()

    goals = []

    if ptype == 'Student':
        # Universal career-growth goals for students
        goals += [
            'Improve your portfolio — add or update 1 project',
            'Update GitHub profile and pin top repos',
            'Apply to 1 internship or opportunity this week',
            'Network with 1 professional or alumni on LinkedIn',
        ]
        if 'web' in field or 'frontend' in field or 'ui' in field or 'ux' in field:
            goals += [
                'Build 1 responsive UI component from scratch',
                'Replicate a Dribbble/Behance design in code',
                'Contribute to 1 open-source frontend project',
            ]
        elif 'ai' in field or 'ml' in field or 'machine' in field or 'data' in field:
            goals += [
                'Complete 1 Kaggle notebook or dataset EDA',
                'Read 1 AI/ML paper or blog (with notes)',
                'Implement 1 algorithm without a library',
            ]
        elif 'mobile' in field or 'android' in field or 'ios' in field or 'flutter' in field:
            goals += [
                'Publish or update 1 app on a store',
                'Implement 1 new screen in your side project',
            ]
        elif 'cyber' in field or 'security' in field:
            goals += [
                'Complete 1 CTF challenge or TryHackMe room',
                'Document 1 vulnerability or concept you studied',
            ]
        elif 'backend' in field or 'fullstack' in field or 'full stack' in field:
            goals += [
                'Build and deploy 1 REST API endpoint',
                'Write 1 test (unit or integration)',
            ]
        else:
            goals += [
                'Learn 1 new technical skill or tool this week',
                'Document learnings — write a blog or notes',
            ]

    elif ptype == 'Working Professional':
        goals += [
            'Update LinkedIn with recent achievements',
            'Apply to 1 senior or stretch opportunity',
            'Reach out to 1 industry contact for a catch-up',
            'Complete 1 module of an online course',
        ]
        if any(k in role for k in ('engineer', 'developer', 'dev', 'software')):
            goals += [
                'Write or improve 1 piece of technical documentation',
                'Review 1 open-source PR or issue',
                'Refactor 1 piece of legacy code',
            ]
        elif any(k in role for k in ('data', 'analyst', 'scientist')):
            goals += [
                'Create 1 data visualization or dashboard panel',
                'Automate 1 repetitive reporting task',
            ]
        elif any(k in role for k in ('manager', 'lead', 'product')):
            goals += [
                'Write 1 clear project brief or user story',
                'Conduct 1 retro note or team check-in',
            ]
        else:
            goals += [
                'Share 1 insight with your team or network',
                'Identify 1 process improvement in your workflow',
            ]

    elif ptype == 'Content Creator':
        goals += [
            'Upload or schedule 1 content piece this week',
            'Engage with 10 comments or DMs in your community',
            'Research 3 trending topics in your niche',
            'Collaborate with 1 creator or brand',
            'Review analytics and note 1 key learning',
        ]

    else:  # Other / fallback
        goals += [
            'Define your top 3 career goals for this month',
            'Spend 1 hour on skill development or a course',
            'Update your professional profile or resume',
            'Connect with 1 person in your target industry',
        ]

    return goals


def _sync_career_goals(db, uid, profile, today):
    """
    Idempotently insert generated career goals into profession_tasks.
    Rules:
      - category = 'career', task_date = today
      - Never insert a goal whose title already exists for this user+date (case-insensitive)
      - Never delete or touch existing tasks (completed or not)
    Returns count of newly inserted goals.
    """
    goals = _generate_career_goals(profile)
    if not goals:
        return 0

    # Existing career task titles for today (case-insensitive)
    try:
        existing_rows = db.execute(
            "SELECT LOWER(title) AS ltitle FROM profession_tasks "
            "WHERE user_id=? AND task_date=? AND category='career'",
            (uid, today)
        ).fetchall()
        existing_titles = {r['ltitle'] for r in existing_rows}
    except Exception:
        existing_titles = set()

    inserted = 0
    for title in goals:
        if title.lower().strip() not in existing_titles:
            try:
                db.execute(
                    "INSERT INTO profession_tasks (user_id, title, task_date, category) "
                    "VALUES (?, ?, ?, 'career')",
                    (uid, title, today)
                )
                existing_titles.add(title.lower().strip())
                inserted += 1
            except Exception as e:
                print(f"Goal insert error: {e}")
    if inserted:
        db.commit()
    return inserted


@app.route('/profile/setup', methods=['GET', 'POST'])
@login_required
def profile_setup():
    """Profile setup/edit page — safe, isolated, does not touch existing tables."""
    db = get_db()
    uid = session['user_id']

    if request.method == 'POST':
        # Validate required field
        profession_type = (request.form.get('profession_type') or '').strip()
        if not profession_type:
            flash('Please select your profession type.', 'error')
            return redirect(url_for('profile_setup'))

        full_name       = (request.form.get('full_name') or '').strip()
        field_of_interest = (request.form.get('field_of_interest') or '').strip()

        # Student fields
        degree          = (request.form.get('degree') or '').strip()
        branch          = (request.form.get('branch') or '').strip()
        year_of_study   = (request.form.get('year_of_study') or '').strip()
        institution     = (request.form.get('institution') or '').strip()

        # Working professional fields
        industry        = (request.form.get('industry') or '').strip()
        role            = (request.form.get('role') or '').strip()
        experience_years = (request.form.get('experience_years') or '').strip()

        try:
            # Check existing profile
            existing = _get_user_profile(db, uid)
            if existing:
                db.execute('''
                    UPDATE user_profiles SET
                        full_name=?, profession_type=?, field_of_interest=?,
                        degree=?, branch=?, year_of_study=?, institution=?,
                        industry=?, role=?, experience_years=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE user_id=?
                ''', (full_name, profession_type, field_of_interest,
                      degree, branch, year_of_study, institution,
                      industry, role, experience_years, uid))
            else:
                db.execute('''
                    INSERT INTO user_profiles
                        (user_id, full_name, profession_type, field_of_interest,
                         degree, branch, year_of_study, institution,
                         industry, role, experience_years)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (uid, full_name, profession_type, field_of_interest,
                      degree, branch, year_of_study, institution,
                      industry, role, experience_years))
            db.commit()
            flash('Profile saved successfully!', 'success')
            return redirect(url_for('career'))
        except Exception as e:
            print(f"Profile save error: {e}")
            flash('An error occurred saving your profile. Please try again.', 'error')
            return redirect(url_for('profile_setup'))

    # GET — load existing profile values for pre-filling
    profile = _get_user_profile(db, uid)
    return render_template('profile_setup.html', profile=profile)





@app.route('/api/profession/profile', methods=['GET'])
@login_required
def get_profession_profile():
    """Return current user's profession profile as JSON."""
    db = get_db()
    profile = _get_user_profile(db, session['user_id'])
    if not profile:
        return jsonify({'has_profile': False})
    return jsonify({
        'has_profile': True,
        'profession_type': profile['profession_type'] or '',
        'full_name': profile['full_name'] or '',
        'field_of_interest': profile['field_of_interest'] or '',
    })


# ── Career Section (Editable Profile) ───────────────────────────────────────

@app.route('/career')
@login_required
def career():
    """Career profile page — editable, prefilled from user_profiles."""
    db = get_db()
    uid = session['user_id']
    today = datetime.date.today().isoformat()

    profile = _get_user_profile(db, uid)

    # Live profession stats (all tasks today, both core + career categories)
    try:
        prof_tasks = db.execute(
            'SELECT is_completed FROM profession_tasks WHERE user_id=? AND task_date=?',
            (uid, today)
        ).fetchall()
        prof_total = len(prof_tasks)
        prof_done  = sum(1 for t in prof_tasks if t['is_completed'])
        prof_pct   = round((prof_done / prof_total * 100) if prof_total else 0)
    except Exception:
        prof_total = prof_done = prof_pct = 0

    # All-time counts
    try:
        all_tasks = db.execute(
            'SELECT is_completed FROM profession_tasks WHERE user_id=?', (uid,)
        ).fetchall()
        all_total = len(all_tasks)
        all_done  = sum(1 for t in all_tasks if t['is_completed'])
    except Exception:
        all_total = all_done = 0

    return render_template('career.html',
                           profile=profile,
                           prof_pct=prof_pct,
                           prof_done=prof_done,
                           prof_total=prof_total,
                           all_total=all_total,
                           all_done=all_done,
                           today=today)


@app.route('/career/update', methods=['POST'])
@login_required
def career_update():
    """Save all editable career profile fields. Only touches user_profiles."""
    db = get_db()
    uid = session['user_id']

    # Safely read every field — never crash on missing input
    def g(f, maxlen=120):
        return (request.form.get(f) or '').strip()[:maxlen]

    full_name       = g('full_name')
    date_of_birth   = g('date_of_birth', 12)
    profession_type = g('profession_type')
    
    # Map "Other" to custom input
    if profession_type == 'Other':
        other_val = g('profession_type_other')
        if other_val:
            profession_type = other_val

    field_of_interest = g('field_of_interest')
    location        = g('location', 120)
    website         = g('website', 255)
    degree          = g('degree')
    branch          = g('branch')
    year_of_study   = g('year_of_study')
    institution     = g('institution')
    industry        = g('industry')
    role            = g('role')
    experience_years= g('experience_years')
    bio             = (request.form.get('bio') or '').strip()[:500]

    try:
        existing = _get_user_profile(db, uid)
        if existing:
            db.execute('''
                UPDATE user_profiles SET
                    full_name=?, date_of_birth=?, location=?, website=?, profession_type=?,
                    field_of_interest=?, degree=?, branch=?,
                    year_of_study=?, institution=?, industry=?,
                    role=?, experience_years=?, bio=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=?
            ''', (full_name, date_of_birth, location, website, profession_type,
                  field_of_interest, degree, branch,
                  year_of_study, institution, industry,
                  role, experience_years, bio, uid))
        else:
            db.execute('''
                INSERT INTO user_profiles
                    (user_id, full_name, date_of_birth, location, website, profession_type,
                     field_of_interest, degree, branch, year_of_study,
                     institution, industry, role, experience_years, bio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (uid, full_name, date_of_birth, location, website, profession_type,
                  field_of_interest, degree, branch,
                  year_of_study, institution, industry,
                  role, experience_years, bio))
        db.commit()
        flash('Career profile saved!', 'success')
    except Exception as e:
        print(f"Career update error: {e}")
        flash('Save failed — please try again.', 'error')

    return redirect(url_for('career'))


@app.route('/api/career/bio/update', methods=['POST'])
@login_required
def update_career_bio():
    """Legacy bio-only update endpoint (kept for backwards compat)."""
    data = request.json or {}
    bio = (data.get('bio') or '').strip()[:500]
    db = get_db()
    uid = session['user_id']
    try:
        existing = _get_user_profile(db, uid)
        if existing:
            db.execute(
                'UPDATE user_profiles SET bio=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?',
                (bio, uid)
            )
            db.commit()
            return jsonify({'status': 'success'})
        return jsonify({'status': 'error', 'message': 'Profile not found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    run_schema()
    app.run(debug=True)

