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
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS streaks (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        streak_count INTEGER DEFAULT 0,
        last_activity_date DATE
    );
    """)

    # ensure default user
    cur.execute("SELECT id FROM users WHERE username = %s", ('RYUK',))
    if cur.fetchone() is None:
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", 
                   ('RYUK', 'THAD1560'))
        conn.commit()

    cur.close()
    conn.close()

# ---------- HELPER FUNCTIONS ----------
def get_user_id(username, password):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s AND password = %s", 
                       (username, password))
            row = cur.fetchone()
            return row[0] if row else None

def get_user_progress(user_id):
    progress = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT subject, type, completed, total 
                FROM progress 
                WHERE user_id = %s
            """, (user_id,))
            
            for row in cur.fetchall():
                subject, typ, completed, total = row
                key = f"{subject}-{typ}"
                progress[key] = {"completed": completed, "total": total}
    
    return progress

def update_user_progress(user_id, subject, typ, completed):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO progress (user_id, subject, type, completed, total)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id, subject, type) 
                DO UPDATE SET completed = %s, last_updated = CURRENT_TIMESTAMP
            """, (user_id, subject, typ, completed, 30, completed))
            conn.commit()

def update_streak(user_id, activity_date):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get current streak
            cur.execute("""
                SELECT streak_count, last_activity_date 
                FROM streaks 
                WHERE user_id = %s
            """, (user_id,))
            row = cur.fetchone()
            
            if row:
                streak_count, last_date = row
                # Check if activity is consecutive
                if last_date and (activity_date - last_date).days == 1:
                    streak_count += 1
                elif last_date and (activity_date - last_date).days > 1:
                    streak_count = 1  # Reset streak if gap > 1 day
                else:
                    streak_count = max(streak_count, 1)
            else:
                streak_count = 1
                
            # Update streak
            cur.execute("""
                INSERT INTO streaks (user_id, streak_count, last_activity_date)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) 
                DO UPDATE SET streak_count = %s, last_activity_date = %s
            """, (user_id, streak_count, activity_date, streak_count, activity_date))
            conn.commit()
            
            return streak_count

# ---------- ROUTES ----------
@app.route('/')
def index():
    return send_from_directory('.', 'tracker.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    user_id = get_user_id(username, password)
    if user_id:
        return jsonify({"success": True, "user_id": user_id})
    else:
        return jsonify({"success": False, "message": "Invalid credentials"})

@app.route('/api/progress', methods=['GET'])
def progress():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "user_id required"})
    
    progress_data = get_user_progress(user_id)
    return jsonify({"success": True, "progress": progress_data})

@app.route('/api/submit_daily', methods=['POST'])
def submit_daily():
    data = request.get_json()
    user_id = data.get('user_id')
    class_level = data.get('class_level')
    lectures = data.get('lectures', 0)
    dpp = data.get('dpp', 0)
    today = date.today()
    
    if not user_id or class_level is None:
        return jsonify({"success": False, "message": "user_id and class_level required"})
    
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Check if entry exists for today
                cur.execute("""
                    SELECT id FROM daily_progress 
                    WHERE user_id = %s AND class_level = %s AND date = %s
                """, (user_id, class_level, today))
                
                if cur.fetchone():
                    # Update existing entry
                    cur.execute("""
                        UPDATE daily_progress 
                        SET lectures = %s, dpp = %s 
                        WHERE user_id = %s AND class_level = %s AND date = %s
                    """, (lectures, dpp, user_id, class_level, today))
                else:
                    # Insert new entry
                    cur.execute("""
                        INSERT INTO daily_progress (user_id, class_level, date, lectures, dpp)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (user_id, class_level, today, lectures, dpp))
                
                # Update subject progress based on class level
                if class_level == 12:
                    if lectures > 0:
                        update_user_progress(user_id, 'maths', 'lectures', 
                                            get_user_progress(user_id).get('maths-lectures', {}).get('completed', 0) + lectures)
                    if dpp > 0:
                        update_user_progress(user_id, 'maths', 'dpp', 
                                            get_user_progress(user_id).get('maths-dpp', {}).get('completed', 0) + dpp)
                elif class_level == 11:
                    if lectures > 0:
                        update_user_progress(user_id, 'maths11', 'lectures', 
                                            get_user_progress(user_id).get('maths11-lectures', {}).get('completed', 0) + lectures)
                    if dpp > 0:
                        update_user_progress(user_id, 'maths11', 'dpp', 
                                            get_user_progress(user_id).get('maths11-dpp', {}).get('completed', 0) + dpp)
                
                # Update streak if there was activity
                if lectures > 0 or dpp > 0:
                    streak = update_streak(user_id, today)
                else:
                    # Get current streak without updating
                    cur.execute("SELECT streak_count FROM streaks WHERE user_id = %s", (user_id,))
                    row = cur.fetchone()
                    streak = row[0] if row else 0
                
                conn.commit()
                
        return jsonify({"success": True, "streak": streak})
    
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/daily_records', methods=['GET'])
def daily_records():
    user_id = request.args.get('user_id')
    class_level = request.args.get('class_level')
    
    if not user_id:
        return jsonify({"success": False, "message": "user_id required"})
    
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if class_level:
                    cur.execute("""
                        SELECT date, class_level, lectures, dpp 
                        FROM daily_progress 
                        WHERE user_id = %s AND class_level = %s
                        ORDER BY date DESC
                    """, (user_id, class_level))
                else:
                    cur.execute("""
                        SELECT date, class_level, lectures, dpp 
                        FROM daily_progress 
                        WHERE user_id = %s
                        ORDER BY date DESC
                    """, (user_id,))
                
                records = []
                for row in cur.fetchall():
                    records.append({
                        "date": row[0].strftime('%Y-%m-%d'),
                        "class_level": row[1],
                        "lectures": row[2],
                        "dpp": row[3]
                    })
                
        return jsonify({"success": True, "records": records})
    
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/streak', methods=['GET'])
def streak():
    user_id = request.args.get('user_id')
    
    if not user_id:
        return jsonify({"success": False, "message": "user_id required"})
    
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT streak_count FROM streaks WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                streak_count = row[0] if row else 0
                
        return jsonify({"success": True, "streak": streak_count})
    
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/admin/update_12th', methods=['POST'])
def admin_update_12th():
    data = request.get_json()
    user_id = data.get('user_id')
    updates = data.get('updates', {})
    
    if not user_id:
        return jsonify({"success": False, "message": "user_id required"})
    
    try:
        # Update maths
        if 'maths-lectures' in updates:
            update_user_progress(user_id, 'maths', 'lectures', int(updates['maths-lectures']))
        if 'maths-dpp' in updates:
            update_user_progress(user_id, 'maths', 'dpp', int(updates['maths-dpp']))
        
        # Update physics
        if 'physics-lectures' in updates:
            update_user_progress(user_id, 'physics', 'lectures', int(updates['physics-lectures']))
        if 'physics-dpp' in updates:
            update_user_progress(user_id, 'physics', 'dpp', int(updates['physics-dpp']))
        
        # Update chemistry
        if 'chemistry-lectures' in updates:
            update_user_progress(user_id, 'chemistry', 'lectures', int(updates['chemistry-lectures']))
        if 'chemistry-dpp' in updates:
            update_user_progress(user_id, 'chemistry', 'dpp', int(updates['chemistry-dpp']))
        
        return jsonify({"success": True})
    
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/admin/update_11th', methods=['POST'])
def admin_update_11th():
    data = request.get_json()
    user_id = data.get('user_id')
    updates = data.get('updates', {})
    
    if not user_id:
        return jsonify({"success": False, "message": "user_id required"})
    
    try:
        # Update maths11
        if 'maths11-lectures' in updates:
            update_user_progress(user_id, 'maths11', 'lectures', int(updates['maths11-lectures']))
        if 'maths11-dpp' in updates:
            update_user_progress(user_id, 'maths11', 'dpp', int(updates['maths11-dpp']))
        
        # Update physics11
        if 'physics11-lectures' in updates:
            update_user_progress(user_id, 'physics11', 'lectures', int(updates['physics11-lectures']))
        if 'physics11-dpp' in updates:
            update_user_progress(user_id, 'physics11', 'dpp', int(updates['physics11-dpp']))
        
        # Update chemistry11
        if 'chemistry11-lectures' in updates:
            update_user_progress(user_id, 'chemistry11', 'lectures', int(updates['chemistry11-lectures']))
        if 'chemistry11-dpp' in updates:
            update_user_progress(user_id, 'chemistry11', 'dpp', int(updates['chemistry11-dpp']))
        
        return jsonify({"success": True})
    
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
