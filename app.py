
# server.py
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
import os

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Database initialization
def init_db():
    conn = sqlite3.connect('lecture_tracker.db')
    c = conn.cursor()
    
    # Create users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL)''')
    
    # Create progress table
    c.execute('''CREATE TABLE IF NOT EXISTS progress
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  subject TEXT NOT NULL,
                  type TEXT NOT NULL,
                  completed INTEGER DEFAULT 0,
                  total INTEGER DEFAULT 30,
                  last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users (id))''')
    
    # Create streaks table
    c.execute('''CREATE TABLE IF NOT EXISTS streaks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  streak_count INTEGER DEFAULT 0,
                  last_activity_date DATE,
                  FOREIGN KEY (user_id) REFERENCES users (id))''')
    
    # Insert default user if not exists
    c.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO users (username, password) VALUES ('admin', 'password')")
        user_id = c.lastrowid
        
        # Insert default progress records
        subjects = [
            ('maths', 'lectures'), ('maths', 'dpp'),
            ('physics', 'lectures'), ('physics', 'dpp'),
            ('chemistry', 'lectures'), ('chemistry', 'dpp'),
            ('maths11', 'lectures'), ('maths11', 'dpp'),
            ('physics11', 'lectures'), ('physics11', 'dpp'),
            ('chemistry11', 'lectures'), ('chemistry11', 'dpp')
        ]
        
        for subject, type_ in subjects:
            total = 30 if type_ == 'lectures' else 20
            c.execute('''INSERT INTO progress (user_id, subject, type, completed, total)
                         VALUES (?, ?, ?, ?, ?)''', 
                     (user_id, subject, type_, 0, total))
        
        # Insert default streak record
        c.execute('''INSERT INTO streaks (user_id, streak_count, last_activity_date)
                     VALUES (?, ?, ?)''', 
                 (user_id, 0, datetime.now().date()))
    
    conn.commit()
    conn.close()

# Database connection helper
def get_db_connection():
    conn = sqlite3.connect('lecture_tracker.db')
    conn.row_factory = sqlite3.Row
    return conn

# Authentication middleware
def authenticate(username, password):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?',
                       (username, password)).fetchone()
    conn.close()
    return user

# Update streak function
def update_streak(user_id):
    conn = get_db_connection()
    streak = conn.execute('SELECT * FROM streaks WHERE user_id = ?', (user_id,)).fetchone()
    today = datetime.now().date()
    
    if streak:
        last_activity = datetime.strptime(streak['last_activity_date'], '%Y-%m-%d').date() if isinstance(streak['last_activity_date'], str) else streak['last_activity_date']
        days_diff = (today - last_activity).days
        
        if days_diff == 0:
            # Already updated today
            new_streak = streak['streak_count']
        elif days_diff == 1:
            # Consecutive day
            new_streak = streak['streak_count'] + 1
        else:
            # Broken streak
            new_streak = 1
        
        conn.execute('''UPDATE streaks SET streak_count = ?, last_activity_date = ?
                        WHERE user_id = ?''', (new_streak, today, user_id))
    else:
        # First activity
        new_streak = 1
        conn.execute('''INSERT INTO streaks (user_id, streak_count, last_activity_date)
                        VALUES (?, ?, ?)''', (user_id, new_streak, today))
    
    conn.commit()
    conn.close()
    return new_streak

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    user = authenticate(username, password)
    if user:
        return jsonify({'success': True, 'user_id': user['id']})
    else:
        return jsonify({'success': False, 'message': 'Invalid credentials'})

@app.route('/api/progress', methods=['GET'])
def get_progress():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'User ID required'})
    
    conn = get_db_connection()
    progress = conn.execute('SELECT * FROM progress WHERE user_id = ?', (user_id,)).fetchall()
    conn.close()
    
    progress_data = {}
    for p in progress:
        key = f"{p['subject']}-{p['type']}"
        progress_data[key] = {
            'completed': p['completed'],
            'total': p['total'],
            'percentage': round((p['completed'] / p['total']) * 100) if p['total'] > 0 else 0
        }
    
    return jsonify({'success': True, 'progress': progress_data})

@app.route('/api/progress', methods=['POST'])
def update_progress():
    data = request.get_json()
    user_id = data.get('user_id')
    subject = data.get('subject')
    type_ = data.get('type')
    change = data.get('change', 0)
    
    if not all([user_id, subject, type_]):
        return jsonify({'success': False, 'message': 'Missing parameters'})
    
    conn = get_db_connection()
    
    # Get current progress
    progress = conn.execute('''SELECT * FROM progress 
                              WHERE user_id = ? AND subject = ? AND type = ?''',
                           (user_id, subject, type_)).fetchone()
    
    if not progress:
        return jsonify({'success': False, 'message': 'Progress record not found'})
    
    # Calculate new completed value
    new_completed = max(0, min(progress['total'], progress['completed'] + change))
    
    # Update database
    conn.execute('''UPDATE progress SET completed = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND subject = ? AND type = ?''',
                (new_completed, user_id, subject, type_))
    
    # Update streak if progress was increased
    if change > 0:
        streak_count = update_streak(user_id)
    else:
        streak = conn.execute('SELECT * FROM streaks WHERE user_id = ?', (user_id,)).fetchone()
        streak_count = streak['streak_count'] if streak else 0
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'completed': new_completed,
        'total': progress['total'],
        'percentage': round((new_completed / progress['total']) * 100) if progress['total'] > 0 else 0,
        'streak': streak_count
    })

@app.route('/api/streak', methods=['GET'])
def get_streak():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'User ID required'})
    
    conn = get_db_connection()
    streak = conn.execute('SELECT * FROM streaks WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()
    
    streak_count = streak['streak_count'] if streak else 0
    return jsonify({'success': True, 'streak': streak_count})

@app.route('/api/days_until_dec31_2025', methods=['GET'])
def days_until_dec31_2025():
    target_date = datetime(2025, 12, 31)
    today = datetime.now()
    days_left = (target_date - today).days
    return jsonify({'success': True, 'days_left': days_left})

@app.route('/api/admin/update', methods=['POST'])
def admin_update():
    data = request.get_json()
    user_id = data.get('user_id')
    updates = data.get('updates', {})
    
    if not user_id:
        return jsonify({'success': False, 'message': 'User ID required'})
    
    conn = get_db_connection()
    
    for key, value in updates.items():
        if '-' in key:
            subject, type_ = key.split('-', 1)
            conn.execute('''UPDATE progress SET completed = ?, last_updated = CURRENT_TIMESTAMP
                            WHERE user_id = ? AND subject = ? AND type = ?''',
                        (value, user_id, subject, type_))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Progress updated successfully'})

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
