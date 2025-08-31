# app.py
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import psycopg2
import os
from datetime import datetime, date, timedelta
from urllib.parse import urlparse

app = Flask(__name__, static_folder='.')
CORS(app)

# ---------- DATABASE CONFIG ----------
# Use the External Database URL you provided
DATABASE_URL = os.environ.get('DATABASE_URL') or "postgresql://track_life_user:YSmWqlaIWyR8YDgEm6NfvFzBtYNm2hHZ@dpg-d2qd1efdiees73crvct0-a.oregon-postgres.render.com/track_life"

def get_conn():
    # psycopg2 connect
    return psycopg2.connect(DATABASE_URL)

# ---------- DB INITIALIZATION ----------
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    );
    """)

    # progress table - totals per user/subject/type
    cur.execute("""
    CREATE TABLE IF NOT EXISTS progress (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        type TEXT NOT NULL,
        completed INTEGER DEFAULT 0,
        total INTEGER DEFAULT 30,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # daily_progress table - records of each day submission
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_progress (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        class_level INTEGER NOT NULL, -- 11 or 12
        date DATE NOT NULL,
        lectures INTEGER DEFAULT 0,
        dpp INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # streaks table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS streaks (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        streak_count INTEGER DEFAULT 0,
        last_activity_date DATE
    );
    """)

    # ensure default user (RYUK / THAD1560) exists and default progress rows
    cur.execute("SELECT id FROM users WHERE username = %s", ('RYUK',))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s) RETURNING id", ('RYUK', 'THAD1560'))
        user_id = cur.fetchone()[0]

        # Insert default progress rows for classes and subjects
        subjects_12 = [
            ('maths', 'lectures'), ('maths', 'dpp'),
            ('physics', 'lectures'), ('physics', 'dpp'),
            ('chemistry', 'lectures'), ('chemistry', 'dpp'),
            ('class12', 'lectures'), ('class12', 'dpp') -- /* aggregate */
        ]
        # For class11
        subjects_11 = [
            ('maths11', 'lectures'), ('maths11', 'dpp'),
            ('physics11', 'lectures'), ('physics11', 'dpp'),
            ('chemistry11', 'lectures'), ('chemistry11', 'dpp'),
            ('class11', 'lectures'), ('class11', 'dpp') -- /* aggregate */
        ]
        # In Postgres SQL, comments inline with -- would break when combined. We'll insert separately:
        pass

    conn.commit()

    # Insert default progress records (we separate insertion to avoid SQL comment issues)
    cur.execute("SELECT id FROM users WHERE username=%s", ('RYUK',))
    row = cur.fetchone()
    if row:
        user_id = row[0]
        # Check if progress exists for this user
        cur.execute("SELECT COUNT(*) FROM progress WHERE user_id=%s", (user_id,))
        cnt = cur.fetchone()[0]
        if cnt == 0:
            subjects = [
                ('maths', 'lectures', 0, 30), ('maths', 'dpp', 0, 20),
                ('physics', 'lectures', 0, 30), ('physics', 'dpp', 0, 20),
                ('chemistry', 'lectures', 0, 30), ('chemistry', 'dpp', 0, 20),

                ('maths11', 'lectures', 0, 30), ('maths11', 'dpp', 0, 20),
                ('physics11', 'lectures', 0, 30), ('physics11', 'dpp', 0, 20),
                ('chemistry11', 'lectures', 0, 30), ('chemistry11', 'dpp', 0, 20),

                # Aggregate class level rows
                ('class12', 'lectures', 0, 90), ('class12', 'dpp', 0, 60),
                ('class11', 'lectures', 0, 90), ('class11', 'dpp', 0, 60),
            ]
            for subj, t, comp, tot in subjects:
                cur.execute("""
                INSERT INTO progress (user_id, subject, type, completed, total)
                VALUES (%s, %s, %s, %s, %s)
                """, (user_id, subj, t, comp, tot))

    # ensure streak record exists
    cur.execute("SELECT id FROM streaks WHERE user_id = %s", (row[0],))
    if not cur.fetchone():
        cur.execute("INSERT INTO streaks (user_id, streak_count, last_activity_date) VALUES (%s, %s, %s)",
                    (row[0], 0, None))

    conn.commit()
    cur.close()
    conn.close()

# Call init on import
init_db()

# ---------- HELPERS ----------
def authenticate(username, password):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE username=%s AND password=%s", (username, password))
    r = cur.fetchone()
    cur.close()
    conn.close()
    return r  # None or (id, username)

def update_streak(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT streak_count, last_activity_date FROM streaks WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    today = date.today()

    if row:
        streak_count, last_date = row
        if last_date is None:
            new_streak = 1
        else:
            days_diff = (today - last_date).days
            if days_diff == 0:
                new_streak = streak_count  # already updated today
            elif days_diff == 1:
                new_streak = streak_count + 1
            else:
                new_streak = 1
        cur.execute("UPDATE streaks SET streak_count=%s, last_activity_date=%s WHERE user_id=%s",
                    (new_streak, today, user_id))
    else:
        new_streak = 1
        cur.execute("INSERT INTO streaks (user_id, streak_count, last_activity_date) VALUES (%s, %s, %s)",
                    (user_id, new_streak, today))

    conn.commit()
    cur.close()
    conn.close()
    return new_streak

# ---------- ROUTES ----------
@app.route('/')
def root():
    # serve tracker.html if placed in same folder
    return send_from_directory('.', 'tracker.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password required'}), 400

    user = authenticate(username, password)
    if user:
        return jsonify({'success': True, 'user_id': user[0], 'username': user[1]})
    else:
        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/progress', methods=['GET'])
def api_get_progress():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT subject, type, completed, total, last_updated FROM progress WHERE user_id=%s", (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    progress = {}
    for subj, typ, comp, tot, last in rows:
        key = f"{subj}-{typ}"
        pct = round((comp / tot) * 100) if tot and tot > 0 else 0
        progress[key] = {'completed': comp, 'total': tot, 'percentage': pct, 'last_updated': str(last)}
    return jsonify({'success': True, 'progress': progress})

@app.route('/api/submit_daily', methods=['POST'])
def api_submit_daily():
    """
    Payload:
    {
      "user_id": <int>,
      "class_level": 12 or 11,
      "lectures": <int>,
      "dpp": <int>
    }
    """
    data = request.get_json() or {}
    user_id = data.get('user_id')
    class_level = int(data.get('class_level', 12))
    lectures = int(data.get('lectures', 0))
    dpp = int(data.get('dpp', 0))

    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400

    today = date.today()

    conn = get_conn()
    cur = conn.cursor()
    # Ensure only one record per user per day per class_level. If exists, update it (sum) or return
    cur.execute("SELECT id, lectures, dpp FROM daily_progress WHERE user_id=%s AND date=%s AND class_level=%s",
                (user_id, today, class_level))
    row = cur.fetchone()
    if row:
        dp_id, old_lec, old_dpp = row
        new_lec = max(0, old_lec + lectures)
        new_dpp = max(0, old_dpp + dpp)
        cur.execute("UPDATE daily_progress SET lectures=%s, dpp=%s, created_at=NOW() WHERE id=%s",
                    (new_lec, new_dpp, dp_id))
    else:
        cur.execute("INSERT INTO daily_progress (user_id, class_level, date, lectures, dpp) VALUES (%s,%s,%s,%s,%s)",
                    (user_id, class_level, today, lectures, dpp))

    # Update aggregate progress rows for class level (class12/class11)
    class_key = f"class{class_level}"
    # Add to lectures and dpp completed totals, but cap at 'total' column
    # Update lectures
    cur.execute("SELECT id, completed, total FROM progress WHERE user_id=%s AND subject=%s AND type=%s",
                (user_id, class_key, 'lectures'))
    p = cur.fetchone()
    if p:
        pid, completed, total = p
        new_completed = min(total, completed + lectures)
        cur.execute("UPDATE progress SET completed=%s, last_updated=NOW() WHERE id=%s", (new_completed, pid))
    # Update dpp
    cur.execute("SELECT id, completed, total FROM progress WHERE user_id=%s AND subject=%s AND type=%s",
                (user_id, class_key, 'dpp'))
    p2 = cur.fetchone()
    if p2:
        pid2, completed2, total2 = p2
        new_completed2 = min(total2, completed2 + dpp)
        cur.execute("UPDATE progress SET completed=%s, last_updated=NOW() WHERE id=%s", (new_completed2, pid2))

    # Also update streak (only when user submits daily progress with any positive lectures or dpp)
    streak_value = None
    if lectures > 0 or dpp > 0:
        streak_value = update_streak(user_id)

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'success': True, 'message': 'Daily progress recorded', 'streak': streak_value})

@app.route('/api/daily_records', methods=['GET'])
def api_daily_records():
    user_id = request.args.get('user_id')
    class_level = request.args.get('class_level')  # optional
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400

    conn = get_conn()
    cur = conn.cursor()
    if class_level:
        cur.execute("SELECT date, lectures, dpp, class_level FROM daily_progress WHERE user_id=%s AND class_level=%s ORDER BY date DESC",
                    (user_id, int(class_level)))
    else:
        cur.execute("SELECT date, lectures, dpp, class_level FROM daily_progress WHERE user_id=%s ORDER BY date DESC",
                    (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    records = []
    for d, l, dp, cl in rows:
        records.append({'date': str(d), 'lectures': l, 'dpp': dp, 'class_level': cl})
    return jsonify({'success': True, 'records': records})

@app.route('/api/streak', methods=['GET'])
def api_get_streak():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT streak_count, last_activity_date FROM streaks WHERE user_id=%s", (user_id,))
    r = cur.fetchone()
    cur.close()
    conn.close()
    if r:
        return jsonify({'success': True, 'streak': r[0], 'last_activity_date': str(r[1])})
    else:
        return jsonify({'success': True, 'streak': 0})

# ---------- ADMIN ENDPOINTS ----------
@app.route('/api/admin/update_12th', methods=['POST'])
def admin_update_12th():
    """
    Payload:
    {
      "user_id": <int>,
      "updates": { "maths-lectures": 10, "physics-dpp": 3, ... }
    }
    This updates only 12th class related subjects (maths, physics, chemistry and class12 aggregate rows)
    """
    data = request.get_json() or {}
    user_id = data.get('user_id')
    updates = data.get('updates', {})
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400

    conn = get_conn()
    cur = conn.cursor()
    for key, value in updates.items():
        if '-' in key:
            subject, typ = key.split('-', 1)
            # only allow 12th subjects or class12
            allowed = ['maths', 'physics', 'chemistry', 'class12']
            if subject not in allowed:
                continue
            cur.execute("UPDATE progress SET completed=%s, last_updated=NOW() WHERE user_id=%s AND subject=%s AND type=%s",
                        (int(value), user_id, subject, typ))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'message': '12th progress updated'})

@app.route('/api/admin/update_11th', methods=['POST'])
def admin_update_11th():
    """
    Similar to update_12th but for 11th class (maths11, physics11, chemistry11, class11)
    """
    data = request.get_json() or {}
    user_id = data.get('user_id')
    updates = data.get('updates', {})
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400

    conn = get_conn()
    cur = conn.cursor()
    for key, value in updates.items():
        if '-' in key:
            subject, typ = key.split('-', 1)
            allowed = ['maths11', 'physics11', 'chemistry11', 'class11']
            if subject not in allowed:
                continue
            cur.execute("UPDATE progress SET completed=%s, last_updated=NOW() WHERE user_id=%s AND subject=%s AND type=%s",
                        (int(value), user_id, subject, typ))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'message': '11th progress updated'})

# Generic admin update route (keeps backward compatibility)
@app.route('/api/admin/update', methods=['POST'])
def admin_update():
    data = request.get_json() or {}
    user_id = data.get('user_id')
    updates = data.get('updates', {})
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400
    conn = get_conn()
    cur = conn.cursor()
    for key, value in updates.items():
        if '-' in key:
            subject, typ = key.split('-', 1)
            cur.execute("UPDATE progress SET completed=%s, last_updated=NOW() WHERE user_id=%s AND subject=%s AND type=%s",
                        (int(value), user_id, subject, typ))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'message': 'Progress updated'})

# ---------- RUN ----------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
