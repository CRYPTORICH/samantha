"""
Samantha Quince — RSVP Backend
Minimal Flask server for invitation RSVPs
Run: python server.py
"""
import json, os
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)
DATA_FILE = Path(__file__).parent / "rsvp_data.json"

def load_entries():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_entries(entries):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

@app.route("/")
def invitation():
    return send_from_directory(".", "invitation.html")

@app.route("/admin")
def admin():
    return send_from_directory(".", "admin.html")

@app.route("/api/rsvp", methods=["POST"])
def rsvp():
    data = request.get_json(force=True)
    data["timestamp"] = datetime.now().isoformat()
    data["_id"] = datetime.now().strftime("%Y%m%d%H%M%S") + str(os.urandom(2).hex())

    entries = load_entries()
    entries.append(data)
    save_entries(entries)

    return jsonify({"success": True, "id": data["_id"]}), 201

@app.route("/api/rsvp", methods=["GET"])
def get_rsvps():
    return jsonify(load_entries())

if __name__ == "__main__":
    print("🦋 Samantha Quince — RSVP Server")
    print("   Invitación: http://localhost:5050/")
    print("   Admin:      http://localhost:5050/admin")
    app.run(host="0.0.0.0", port=5050, debug=True)
