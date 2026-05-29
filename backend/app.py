from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3, os, datetime

app = Flask(__name__)
CORS(app)

DB = os.path.join(os.path.dirname(__file__), 'rsvp.db')

def init():
    with sqlite3.connect(DB) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS guests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT,
            guests INTEGER DEFAULT 0,
            message TEXT,
            created_at TEXT
        )''')

@app.route('/')
def home():
    return jsonify({"ok": True, "app": "Samantha Quince RSVP"})

@app.route('/rsvp', methods=['POST'])
def submit():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    contact = (data.get('contact') or '').strip()
    guests = int(data.get('guests') or 0)
    message = (data.get('message') or '').strip()
    now = datetime.datetime.utcnow().isoformat()
    with sqlite3.connect(DB) as c:
        c.execute(
            'INSERT INTO guests (name,contact,guests,message,created_at) VALUES (?,?,?,?,?)',
            (name, contact, guests, message, now)
        )
    return jsonify({"ok": True})

@app.route('/rsvp', methods=['GET'])
def list_guests():
    with sqlite3.connect(DB) as c:
        rows = c.execute(
            'SELECT name,contact,guests,message,created_at FROM guests ORDER BY created_at DESC'
        ).fetchall()
    return jsonify([{
        "name": r[0], "contact": r[1], "guests": r[2],
        "message": r[3], "date": r[4]
    } for r in rows])

init()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
