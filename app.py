from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import psycopg
import os
from datetime import datetime, date

app = Flask(__name__, static_folder='.')
CORS(app)

# ---------- DATABASE CONFIG ----------
DATABASE_URL = os.environ.get('DATABASE_URL') or \
    "postgresql://track_life_user:YSmWqlaIWyR8YDgEm6NfvFzBtYNm2hHZ@dpg-d2qd1efdiees73crvct0-a.oregon-postgres.render.com/track_life"

def get_conn():
    return psycopg.connect(DATABASE_URL)

# ---------- DB INITIALIZATION ----------
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS progress (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        type TEXT NOT NULL,
        completed INTEGER DEFAULT 0,
        total INTEGER DEFAULT 30,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, subject, type)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_progress (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        class_level INTEGER NOT NULL, -- 11 or 12
        date DATE NOT NULL,
        lectures INTEGER DEFAULT 0,
        dpp INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, class_level, date)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS streaks (
        id SERIAL PRIMARY KEY,
        user_id INTEGER UNIQUE NOT NULL,
        streak_count INTEGER DEFAULT 0,
        last_activity_date DATE
    );
    """)

    # ensure default user
    cur.execute("SELECT id FROM users WHERE username = %s", ('RYUK',))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s) RETURNING id",
                    ('RYUK', 'THAD1560'))
        user_id = cur.fetchone()[0]
    else:
        user_id = row[0]

    # Insert default progress rows if missing
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

            ('class12', 'lectures', 0, 90), ('class12', 'dpp', 0, 60),
            ('class11', 'lectures', 0, 90), ('class11', 'dpp', 0, 60),
        ]
        for subj, t, comp, tot in subjects:
            cur.execute("""
            INSERT INTO progress (user_id, subject, type, completed, total)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, subject, type) 
            DO UPDATE SET completed = EXCLUDED.completed, total = EXCLUDED.total
            """, (user_id, subj, t, comp, tot))

    # Ensure streak record exists
    cur.execute("SELECT id FROM streaks WHERE user_id=%s", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO streaks (user_id, streak_count, last_activity_date) VALUES (%s, %s, %s)",
                    (user_id, 0, None))

    conn.commit()
    cur.close()
    conn.close()

# run init
init_db()

# ---------- HELPERS ----------
def authenticate(username, password):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE username=%s AND password=%s", (username, password))
    r = cur.fetchone()
    cur.close()
    conn.close()
    return r

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
                new_streak = streak_count
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
    
    try:
        # Update or insert daily progress
        cur.execute("""
            INSERT INTO daily_progress (user_id, class_level, date, lectures, dpp)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, class_level, date) 
            DO UPDATE SET lectures = daily_progress.lectures + EXCLUDED.lectures,
                         dpp = daily_progress.dpp + EXCLUDED.dpp,
                         created_at = NOW()
            RETURNING id, lectures, dpp
        """, (user_id, class_level, today, lectures, dpp))
        
        row = cur.fetchone()
        if not row:
            return jsonify({'success': False, 'message': 'Failed to update daily progress'}), 500

        class_key = f"class{class_level}"
        subject_prefix = "" if class_level == 12 else "11"
        
        # Update subject-specific progress for lectures
        if lectures > 0:
            subjects = ['maths', 'physics', 'chemistry'] if class_level == 12 else ['maths11', 'physics11', 'chemistry11']
            for subject in subjects:
                cur.execute("""
                    UPDATE progress 
                    SET completed = LEAST(total, completed + %s), last_updated = NOW()
                    WHERE user_id = %s AND subject = %s AND type = 'lectures'
                """, (lectures, user_id, subject))
        
        # Update subject-specific progress for DPP
        if dpp > 0:
            subjects = ['maths', 'physics', 'chemistry'] if class_level == 12 else ['maths11', 'physics11', 'chemistry11']
            for subject in subjects:
                cur.execute("""
                    UPDATE progress 
                    SET completed = LEAST(total, completed + %s), last_updated = NOW()
                    WHERE user_id = %s AND subject = %s AND type = 'dpp'
                """, (dpp, user_id, subject))
        
        # Update class-level progress
        if lectures > 0:
            cur.execute("""
                UPDATE progress 
                SET completed = LEAST(total, completed + %s), last_updated = NOW()
                WHERE user_id = %s AND subject = %s AND type = 'lectures'
            """, (lectures, user_id, class_key))
        
        if dpp > 0:
            cur.execute("""
                UPDATE progress 
                SET completed = LEAST(total, completed + %s), last_updated = NOW()
                WHERE user_id = %s AND subject = %s AND type = 'dpp'
            """, (dpp, user_id, class_key))

        streak_value = None
        if lectures > 0 or dpp > 0:
            streak_value = update_streak(user_id)

        conn.commit()
        return jsonify({'success': True, 'message': 'Daily progress recorded', 'streak': streak_value})
    
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500
    
    finally:
        cur.close()
        conn.close()

@app.route('/api/daily_records', methods=['GET'])
def api_daily_records():
    user_id = request.args.get('user_id')
    class_level = request.args.get('class_level')
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400

    conn = get_conn()
    cur = conn.cursor()
    try:
        if class_level:
            cur.execute("SELECT date, lectures, dpp, class_level FROM daily_progress WHERE user_id=%s AND class_level=%s ORDER BY date DESC",
                        (user_id, int(class_level)))
        else:
            cur.execute("SELECT date, lectures, dpp, class_level FROM daily_progress WHERE user_id=%s ORDER BY date DESC",
                        (user_id,))
        rows = cur.fetchall()
        
        records = [{'date': str(d), 'lectures': l, 'dpp': dp, 'class_level': cl} for d, l, dp, cl in rows]
        return jsonify({'success': True, 'records': records})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500
    
    finally:
        cur.close()
        conn.close()

@app.route('/api/streak', methods=['GET'])
def api_get_streak():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400
    
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT streak_count, last_activity_date FROM streaks WHERE user_id=%s", (user_id,))
        r = cur.fetchone()
        if r:
            return jsonify({'success': True, 'streak': r[0], 'last_activity_date': str(r[1])})
        else:
            return jsonify({'success': True, 'streak': 0})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500
    
    finally:
        cur.close()
        conn.close()

# ---------- ADMIN ENDPOINTS ----------
@app.route('/api/admin/update_12th', methods=['POST'])
def admin_update_12th():
    data = request.get_json() or {}
    user_id = data.get('user_id')
    updates = data.get('updates', {})
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400

    conn = get_conn()
    cur = conn.cursor()
    try:
        for key, value in updates.items():
            if '-' in key:
                subject, typ = key.split('-', 1)
                if subject not in ['maths', 'physics', 'chemistry', 'class12']:
                    continue
                cur.execute("""
                    UPDATE progress SET completed=%s, last_updated=NOW() 
                    WHERE user_id=%s AND subject=%s AND type=%s
                """, (int(value), user_id, subject, typ))
        
        conn.commit()
        return jsonify({'success': True, 'message': '12th progress updated'})
    
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500
    
    finally:
        cur.close()
        conn.close()

@app.route('/api/admin/update_11th', methods=['POST'])
def admin_update_11th():
    data = request.get_json() or {}
    user_id = data.get('user_id')
    updates = data.get('updates', {})
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400

    conn = get_conn()
    cur = conn.cursor()
    try:
        for key, value in updates.items():
            if '-' in key:
                subject, typ = key.split('-', 1)
                if subject not in ['maths11', 'physics11', 'chemistry11', 'class11']:
                    continue
                cur.execute("""
                    UPDATE progress SET completed=%s, last_updated=NOW() 
                    WHERE user_id=%s AND subject=%s AND type=%s
                """, (int(value), user_id, subject, typ))
        
        conn.commit()
        return jsonify({'success': True, 'message': '11th progress updated'})
    
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500
    
    finally:
        cur.close()
        conn.close()

# ---------- RUN ----------
if __name__ == '__main__':
    # For local dev
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
