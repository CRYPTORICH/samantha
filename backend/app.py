from flask import Flask, request, jsonify
from flask_cors import CORS
import os, datetime, json, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)

DATA_FILE = os.path.join(os.path.dirname(__file__), 'rsvp_data.json')

# ── Email ──────────────────────────────────────────────────
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("GMAIL_ADDRESS", "")
SMTP_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")
FROM_NAME = "Samantha · Quince Años"
FROM_EMAIL = SMTP_USER

EVENT_DATE = datetime.datetime(2026, 10, 3, 15, 0, 0)
EVENT = {
    "date_str": "Sábado 3 de Octubre 2026 / Saturday, October 3, 2026",
    "time": "3:00 PM",
    "venue": "Fairwind Baptist Church",
    "address": "801 Seymour Rd · Bear, DE 19701",
}

def send_email(to_email, subject, body_html):
    if not SMTP_PASS or not to_email:
        print(f"[email] Skipping — no creds or no recipient")
        return False
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html"))
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        server.quit()
        print(f"[email] ✓ Sent to {to_email}")
        return True
    except Exception as e:
        print(f"[email] ✗ Failed {to_email}: {e}")
        return False


# ── Data Store (JSON file) ─────────────────────────────────
# Persists across Render restarts. Wiped on deploys — but cron
# syncs to GitHub so the committed rsvp_data.json serves as seed.

def read_data():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def write_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Email Templates ────────────────────────────────────────
def confirmation_email(name):
    days = (EVENT_DATE - datetime.datetime.now()).days
    return (
        f"🎀 ¡Gracias, {name}! · Thank You, {name}!",
        f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h1 style="font-family:'Georgia',serif;color:#dcc898;font-size:1.8rem;text-align:center;margin:0 0 4px">✨ ¡Confirmado!</h1>
<p style="text-align:center;color:rgba(236,228,212,0.5);font-size:0.8rem;margin:0 0 24px">Tu asistencia está registrada · Your RSVP is confirmed</p>
<p style="font-size:1.05rem;line-height:1.8;text-align:center">
  <strong>{name}</strong>, nos llena de alegría que nos acompañes.<br>
  <span style="color:rgba(236,228,212,0.5);font-size:0.9rem">We're so happy you'll be joining us.</span>
</p>
<div style="background:rgba(6,8,5,0.6);border:1px solid rgba(196,160,74,0.12);border-radius:10px;padding:24px;margin:28px 0;text-align:center">
  <p style="margin:0 0 8px;color:rgba(0,168,107,0.5);font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase">Detalles · Details</p>
  <p style="margin:4px 0;font-size:1.1rem">📅 {EVENT['date_str']}</p>
  <p style="margin:4px 0">🕒 {EVENT['time']}</p>
  <p style="margin:4px 0">📍 {EVENT['venue']}</p>
  <p style="margin:4px 0;color:rgba(236,228,212,0.5);font-size:0.85rem">{EVENT['address']}</p>
</div>
<div style="text-align:center;margin:24px 0">
  <p style="font-size:1.4rem;color:#dcc898;margin:0">Faltan <strong>{days}</strong> días</p>
  <p style="font-size:0.7rem;color:rgba(236,228,212,0.35);margin:4px 0 0">{days} days until the celebration</p>
</div>
</div>"""
    )


FOLLOWUP_TEMPLATES = [
    {
        "subject": "🎀 Recordatorio · Samantha Quince Años",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">Hola {name} 👋</h2>
<p style="text-align:center;font-size:1.05rem;line-height:1.8">Solo un recordatorio — los Quince de Samantha se acercan.<br><span style="color:rgba(236,228,212,0.5);font-size:0.85rem">Just a friendly reminder — Samantha's Quince Años is coming up.</span></p>
<div style="text-align:center;margin:24px 0"><p style="font-size:1.6rem;color:#dcc898;margin:0"><strong>{days}</strong> días</p></div>
<p style="text-align:center;font-size:0.9rem">📅 {EVENT['date_str']}<br>🕒 {EVENT['time']} · 📍 {EVENT['venue']}</p>
</div>"""
    },
    {
        "subject": "🎀 Dos Semanas · Samantha Quince Años",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">¡Quedan {days} días! 🌟</h2>
<p style="text-align:center;font-size:1.05rem;line-height:1.8">{name}, ya casi estamos. El gran día de Samantha está a la vuelta de la esquina.</p>
<div style="background:rgba(0,92,63,0.15);border:1px solid rgba(0,168,107,0.2);border-radius:10px;padding:20px;margin:24px 0;text-align:center">
<p style="margin:0;font-size:0.9rem">📍 {EVENT['venue']}</p><p style="margin:4px 0">🕒 {EVENT['time']}</p></div>
</div>"""
    },
    {
        "subject": "🎀 Una Semana · Samantha Quince Años",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">¡Una semana! 💃</h2>
<p style="text-align:center;font-size:1.1rem;line-height:1.8">{name}, este sábado es el día. ¿Estás lista/o?</p>
<div style="text-align:center;margin:24px 0"><p style="font-size:2rem;color:#dcc898;margin:0"><strong>{days}</strong></p><p style="font-size:0.7rem;color:rgba(236,228,212,0.4);margin:2px 0">días</p></div>
<p style="text-align:center;font-size:0.95rem">📅 Sábado 3 de Octubre<br>🕒 3:00 PM<br>📍 {EVENT['venue']}</p>
</div>"""
    },
    {
        "subject": "🎀 Último Recordatorio · Samantha Quince Años",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">¡Ya casi! 🎉</h2>
<p style="text-align:center;font-size:1.05rem;line-height:1.8">{name}, solo quedan <strong style="color:#dcc898">{days} días</strong> para los Quince de Samantha.</p>
<div style="background:rgba(6,8,5,0.6);border:1px solid rgba(196,160,74,0.2);border-radius:10px;padding:24px;margin:24px 0;text-align:center">
<p style="margin:4px 0">📅 Sábado · Saturday, Oct 3</p><p style="margin:4px 0">🕒 3:00 PM</p><p style="margin:4px 0">📍 {EVENT['venue']}</p></div>
</div>"""
    },
]


# ── Routes ─────────────────────────────────────────────────
@app.route('/')
def home():
    return jsonify({"ok": True, "app": "Samantha Quince RSVP", "event": EVENT})


@app.route('/rsvp', methods=['POST'])
def submit():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    entry = {
        "name": name,
        "phone": (data.get('phone') or '').strip(),
        "email": (data.get('email') or '').strip(),
        "address": (data.get('address') or '').strip(),
        "guests": int(data.get('guests') or 0),
        "message": (data.get('message') or '').strip(),
        "date": datetime.datetime.utcnow().isoformat(),
        "confirmation_sent": False,
        "followup_stage": 0,
    }

    all_data = read_data()
    all_data.append(entry)
    write_data(all_data)

    # Send confirmation email
    if entry["email"]:
        subject, body = confirmation_email(name)
        if send_email(entry["email"], subject, body):
            entry["confirmation_sent"] = True
            all_data[-1] = entry
            write_data(all_data)

    return jsonify({
        "ok": True,
        "confirmation_sent": entry["confirmation_sent"],
        "event": EVENT,
    })


@app.route('/rsvp', methods=['GET'])
def list_guests():
    return jsonify(read_data())


@app.route('/cron/send-followups', methods=['GET', 'POST'])
def send_followups():
    now = datetime.datetime.now()
    days_until = (EVENT_DATE - now).days

    if days_until <= 0:
        return jsonify({"ok": True, "message": "Event has passed", "sent": 0})

    all_data = read_data()
    sent_count = 0
    changed = False

    for i, guest in enumerate(all_data):
        email = guest.get("email", "")
        if not email:
            continue
        stage = guest.get("followup_stage", 0)
        if stage >= 4:
            continue

        should_send = False
        new_stage = stage

        if stage == 0 and days_until > 7:
            should_send = True
            new_stage = 1
        elif stage == 1 and days_until <= 20 and days_until > 7:
            should_send = True
            new_stage = 2
        elif stage == 2 and days_until <= 13 and days_until > 3:
            should_send = True
            new_stage = 3
        elif stage == 3 and days_until <= 6 and days_until > 0:
            should_send = True
            new_stage = 4

        if should_send:
            tmpl = FOLLOWUP_TEMPLATES[new_stage - 1]
            if send_email(email, tmpl["subject"], tmpl["body"](guest["name"], days_until)):
                all_data[i]["followup_stage"] = new_stage
                sent_count += 1
                changed = True

    if changed:
        write_data(all_data)

    return jsonify({"ok": True, "days_until_event": days_until, "sent": sent_count})


@app.route('/export', methods=['GET'])
def export_data():
    """Return full data for sync/backup purposes."""
    return jsonify(read_data())


@app.route('/stats', methods=['GET'])
def stats():
    all_data = read_data()
    total_attendees = len(all_data) + sum(g.get("guests", 0) for g in all_data)
    now = datetime.datetime.now()
    return jsonify({
        "total_rsvps": len(all_data),
        "total_attendees": total_attendees,
        "days_until": (EVENT_DATE - now).days,
        "event_date": EVENT_DATE.isoformat(),
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
