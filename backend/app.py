from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3, os, datetime, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)

DB = os.path.join(os.path.dirname(__file__), 'rsvp.db')

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
        print(f"[email] Skipping — no creds or no recipient: {to_email}")
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
        print(f"[email] ✓ Sent to {to_email}: {subject}")
        return True
    except Exception as e:
        print(f"[email] ✗ Failed {to_email}: {e}")
        return False


# ── DB ─────────────────────────────────────────────────────
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
        # Migrate: add new columns if missing
        cur = c.execute("PRAGMA table_info(guests)")
        cols = {row[1] for row in cur.fetchall()}
        if 'phone' not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN phone TEXT DEFAULT ''")
        if 'email' not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN email TEXT DEFAULT ''")
        if 'address' not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN address TEXT DEFAULT ''")
        if 'confirmation_sent' not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN confirmation_sent INTEGER DEFAULT 0")
        if 'followup_stage' not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN followup_stage INTEGER DEFAULT 0")


# ── Email Templates ────────────────────────────────────────
def confirmation_email(name):
    days = (EVENT_DATE - datetime.datetime.now()).days
    return (
        f"🎀 ¡Gracias, {name}! · Thank You, {name}!",
        f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h1 style="font-family:'Georgia',serif;color:#dcc898;font-size:1.8rem;text-align:center;margin:0 0 4px">✨ ¡Confirmado!</h1>
<p style="text-align:center;color:rgba(236,228,212,0.5);font-size:0.8rem;margin:0 0 24px">Tu asistencia está registrada · Your RSVP is confirmed</p>

<p style="font-size:1.05rem;line-height:1.8;text-align:center">
  <strong>{name}</strong>, nos llena de alegría que nos acompañes en este día tan especial.<br>
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

<p style="text-align:center;font-size:0.75rem;color:rgba(236,228,212,0.25);margin-top:32px">
  Te enviaremos un recordatorio cuando se acerque la fecha.<br>
  <span style="font-size:0.7rem">We'll send a reminder as the date approaches.</span>
</p>

<p style="text-align:center;font-size:0.6rem;color:rgba(236,228,212,0.15);margin-top:24px">
  Samantha · Quince Años · 2026
</p>
</div>"""
    )


FOLLOWUP_TEMPLATES = [
    # Stage 0: sent, stage 1: ~48h after RSVP (warm check-in)
    {
        "subject": "🎀 Recordatorio · Save the Date · Samantha Quince Años",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">Hola {name} 👋</h2>
<p style="text-align:center;font-size:1.05rem;line-height:1.8">
  Solo un recordatorio amable — los Quince Años de Samantha se acercan.<br>
  <span style="color:rgba(236,228,212,0.5);font-size:0.85rem">Just a friendly reminder — Samantha's Quince Años is coming up.</span>
</p>
<div style="text-align:center;margin:24px 0">
  <p style="font-size:1.6rem;color:#dcc898;margin:0"><strong>{days}</strong> días · days</p>
</div>
<p style="text-align:center;font-size:0.9rem">📅 {EVENT['date_str']}<br>🕒 {EVENT['time']} · 📍 {EVENT['venue']}</p>
<p style="text-align:center;font-size:0.7rem;color:rgba(236,228,212,0.2);margin-top:28px">No es necesario confirmar de nuevo · No need to re-confirm</p>
</div>"""
    },
    # Stage 2: ~14 days before event
    {
        "subject": "🎀 Dos Semanas · Two Weeks · Samantha Quince Años",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">¡Quedan {days} días! 🌟</h2>
<p style="text-align:center;font-size:1.05rem;line-height:1.8">
  {name}, ya casi estamos. El gran día de Samantha está a la vuelta de la esquina.<br>
  <span style="color:rgba(236,228,212,0.5);font-size:0.85rem">We're almost there — Samantha's big day is right around the corner.</span>
</p>
<div style="background:rgba(0,92,63,0.15);border:1px solid rgba(0,168,107,0.2);border-radius:10px;padding:20px;margin:24px 0;text-align:center">
  <p style="margin:0;font-size:0.9rem">📍 {EVENT['venue']}</p>
  <p style="margin:4px 0;color:rgba(236,228,212,0.5);font-size:0.8rem">{EVENT['address']}</p>
  <p style="margin:4px 0">🕒 {EVENT['time']}</p>
</div>
<p style="text-align:center;font-size:0.7rem;color:rgba(236,228,212,0.2);margin-top:28px">Te esperamos · We can't wait to see you!</p>
</div>"""
    },
    # Stage 3: ~7 days before
    {
        "subject": "🎀 Una Semana · One Week · Samantha Quince Años",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">¡Una semana! · One week! 💃</h2>
<p style="text-align:center;font-size:1.1rem;line-height:1.8">
  {name}, este sábado es el día. ¿Estás lista/o?<br>
  <span style="color:rgba(236,228,212,0.5);font-size:0.85rem">This Saturday is the day — are you ready?</span>
</p>
<div style="text-align:center;margin:24px 0">
  <p style="font-size:2rem;color:#dcc898;margin:0"><strong>{days}</strong></p>
  <p style="font-size:0.7rem;color:rgba(236,228,212,0.4);margin:2px 0">días · days</p>
</div>
<p style="text-align:center;font-size:0.95rem">📅 Sábado 3 de Octubre · Saturday, October 3<br>🕒 3:00 PM<br>📍 {EVENT['venue']}<br>{EVENT['address']}</p>
<p style="text-align:center;font-size:0.8rem;color:#dcc898;margin-top:20px">✨ ¡Nos vemos pronto! · See you soon! ✨</p>
</div>"""
    },
    # Stage 4: ~3 days before
    {
        "subject": "🎀 Último Recordatorio · Final Reminder · Samantha Quince Años",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">¡Ya casi! · Almost there! 🎉</h2>
<p style="text-align:center;font-size:1.05rem;line-height:1.8">
  {name}, solo quedan <strong style="color:#dcc898">{days} días</strong> para los Quince de Samantha.<br>
  <span style="color:rgba(236,228,212,0.5);font-size:0.85rem">Just {days} days until Samantha's Quince Años.</span>
</p>
<div style="background:rgba(6,8,5,0.6);border:1px solid rgba(196,160,74,0.2);border-radius:10px;padding:24px;margin:24px 0;text-align:center">
  <p style="margin:0 0 8px;color:rgba(0,168,107,0.5);font-size:0.6rem;letter-spacing:0.25em;text-transform:uppercase">No olvides · Don't forget</p>
  <p style="margin:4px 0">📅 Sábado · Saturday, Oct 3</p>
  <p style="margin:4px 0">🕒 3:00 PM</p>
  <p style="margin:4px 0">📍 {EVENT['venue']}</p>
  <p style="margin:4px 0;color:rgba(236,228,212,0.5);font-size:0.8rem">{EVENT['address']}</p>
</div>
<p style="text-align:center;font-size:1rem;color:#dcc898;margin-top:20px">🎀 ¡Te esperamos! · We'll be waiting! 🎀</p>
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

    phone = (data.get('phone') or '').strip()
    email = (data.get('email') or '').strip()
    address = (data.get('address') or '').strip()
    guests = int(data.get('guests') or 0)
    message = (data.get('message') or '').strip()
    now = datetime.datetime.utcnow().isoformat()

    with sqlite3.connect(DB) as c:
        c.execute(
            'INSERT INTO guests (name, phone, email, address, contact, guests, message, created_at, confirmation_sent, followup_stage) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)',
            (name, phone, email, address, email or phone, guests, message, now, 0, 0)
        )

    # Send confirmation email immediately if email provided
    confirmation_ok = False
    if email:
        subject, body = confirmation_email(name)
        confirmation_ok = send_email(email, subject, body)
        if confirmation_ok:
            with sqlite3.connect(DB) as c:
                c.execute(
                    "UPDATE guests SET confirmation_sent = 1 WHERE email = ? AND name = ? ORDER BY id DESC LIMIT 1",
                    (email, name)
                )

    return jsonify({
        "ok": True,
        "confirmation_sent": confirmation_ok,
        "event": EVENT,
    })


@app.route('/rsvp', methods=['GET'])
def list_guests():
    with sqlite3.connect(DB) as c:
        rows = c.execute(
            'SELECT name, phone, email, address, contact, guests, message, created_at, confirmation_sent '
            'FROM guests ORDER BY created_at DESC'
        ).fetchall()
    return jsonify([{
        "name": r[0], "phone": r[1], "email": r[2], "address": r[3],
        "contact": r[4], "guests": r[5], "message": r[6], "date": r[7],
        "confirmation_sent": bool(r[8])
    } for r in rows])


@app.route('/cron/send-followups', methods=['GET', 'POST'])
def send_followups():
    """Called by external cron. Sends follow-up emails based on days-until-event."""
    now = datetime.datetime.now()
    days_until = (EVENT_DATE - now).days

    if days_until <= 0:
        return jsonify({"ok": True, "message": "Event has passed", "sent": 0})

    # Only send follow-ups when we're within the campaign windows
    sent_count = 0
    with sqlite3.connect(DB) as c:
        # Get guests with emails who haven't reached max stage
        guests = c.execute(
            'SELECT id, name, email, followup_stage FROM guests '
            'WHERE email IS NOT NULL AND email != "" AND followup_stage < 4'
        ).fetchall()

    for gid, name, email, stage in guests:
        should_send = False
        new_stage = stage

        # Stage 1: 2 days after RSVP (or when >90 days remain)
        # Stage 2: 14-20 days before event
        # Stage 3: 7-13 days before event
        # Stage 4: 3-6 days before event
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
            subject = tmpl["subject"]
            body = tmpl["body"](name, days_until)
            if send_email(email, subject, body):
                with sqlite3.connect(DB) as c:
                    c.execute("UPDATE guests SET followup_stage = ? WHERE id = ?", (new_stage, gid))
                sent_count += 1

    return jsonify({"ok": True, "days_until_event": days_until, "sent": sent_count})


@app.route('/stats', methods=['GET'])
def stats():
    now = datetime.datetime.now()
    days_until = (EVENT_DATE - now).days
    with sqlite3.connect(DB) as c:
        total = c.execute('SELECT COUNT(*) FROM guests').fetchone()[0]
        confirmed = c.execute('SELECT SUM(guests) + COUNT(*) FROM guests').fetchone()
        total_attendees = confirmed[0] if confirmed[0] else 0
    return jsonify({
        "total_rsvps": total,
        "total_attendees": total_attendees,
        "days_until": days_until,
        "event_date": EVENT_DATE.isoformat(),
    })


init()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
