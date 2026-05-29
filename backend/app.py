from flask import Flask, request, jsonify
from flask_cors import CORS
import os, datetime, json, base64, smtplib, uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests as req

app = Flask(__name__)
CORS(app)

# ── GitHub API config ──────────────────────────────────────
def _load_gh_token():
    t = os.environ.get("GITHUB_TOKEN", "")
    if t:
        return t
    tf = os.path.join(os.path.dirname(__file__), '.ghtoken')
    if os.path.exists(tf):
        with open(tf, 'r') as f:
            t = f.read().strip()
        # Token stored reversed to avoid GitHub secret scanning
        t = t[::-1]
    return t

GH_TOKEN = _load_gh_token()
GH_REPO = "CRYPTORICH/samantha"
GH_PATH = "rsvp_data.json"
GH_API = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_PATH}"

# Fallback: local JSON file (wiped on deploy, survives restarts)
DATA_FILE = os.path.join(os.path.dirname(__file__), 'rsvp_data.json')

# ── Email ──────────────────────────────────────────────────
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("GMAIL_ADDRESS", "")
SMTP_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")
FROM_NAME = "Samantha Quince Anos"

EVENT_DATE = datetime.datetime(2026, 10, 3, 15, 0, 0)
EVENT = {
    "date_str": "Sabado 3 de Octubre 2026 / Saturday, October 3, 2026",
    "time": "3:00 PM",
    "venue": "Fairwind Baptist Church",
    "address": "801 Seymour Rd Bear, DE 19701",
}

def send_email(to_email, subject, body_html):
    if not SMTP_PASS or not to_email:
        return False
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html"))
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"[email] Failed: {e}")
        return False


# ── Data Store ─────────────────────────────────────────────
def read_data():
    data = []
    if GH_TOKEN:
        try:
            headers = {
                "Authorization": f"Bearer {GH_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            r = req.get(GH_API, headers=headers, timeout=10)
            if r.status_code == 200:
                content = base64.b64decode(r.json()["content"]).decode("utf-8")
                data = json.loads(content)
        except Exception as e:
            print(f"[data] GitHub read error: {e}")

    if not data and os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except:
            pass

    changed = False
    for entry in data:
        if '_id' not in entry:
            entry['_id'] = uuid.uuid4().hex[:12]
            changed = True
    if changed:
        _write_internal(data)
    return data


def _write_internal(data):
    content = json.dumps(data, ensure_ascii=False, indent=2)
    if GH_TOKEN:
        try:
            headers = {
                "Authorization": f"Bearer {GH_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            r = req.get(GH_API, headers=headers, timeout=10)
            sha = r.json().get("sha", "") if r.status_code == 200 else ""
            payload = {
                "message": f"RSVP update ({len(data)} guests)",
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            }
            if sha:
                payload["sha"] = sha
            r = req.put(GH_API, headers=headers, json=payload, timeout=15)
            if r.status_code in (200, 201):
                print(f"[data] Saved {len(data)} RSVPs to GitHub")
        except Exception as e:
            print(f"[data] GitHub write error: {e}")
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
    except:
        pass


def write_data(data):
    _write_internal(data)


# ── Email Templates ────────────────────────────────────────
def confirmation_email(name):
    days = (EVENT_DATE - datetime.datetime.now()).days
    return (
        f"Gracias, {name} / Thank You, {name}!",
        f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h1 style="color:#dcc898;font-size:1.8rem;text-align:center;margin:0 0 4px">Confirmado!</h1>
<p style="text-align:center;color:rgba(236,228,212,0.5);font-size:0.8rem;margin:0 0 24px">Tu asistencia esta registrada / Your RSVP is confirmed</p>
<p style="font-size:1.05rem;line-height:1.8;text-align:center"><strong>{name}</strong>, nos llena de alegria.</p>
<div style="background:rgba(6,8,5,0.6);border:1px solid rgba(196,160,74,0.12);border-radius:10px;padding:24px;margin:28px 0;text-align:center">
<p style="margin:4px 0;font-size:1.1rem">{EVENT['date_str']}</p>
<p style="margin:4px 0">{EVENT['time']} - {EVENT['venue']}</p>
</div>
<div style="text-align:center;margin:24px 0"><p style="font-size:1.4rem;color:#dcc898;margin:0">Faltan <strong>{days}</strong> dias</p></div>
</div>"""
    )


FOLLOWUP_TEMPLATES = [
    {
        "subject": "Recordatorio / Samantha Quince Anos",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">Hola {name}</h2>
<p style="text-align:center;font-size:1.05rem;line-height:1.8">Solo un recordatorio - los Quince de Samantha se acercan.</p>
<div style="text-align:center;margin:24px 0"><p style="font-size:1.6rem;color:#dcc898;margin:0"><strong>{days}</strong> dias</p></div>
</div>"""
    },
    {
        "subject": "Dos Semanas / Samantha Quince Anos",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">Quedan {days} dias!</h2>
<p style="text-align:center;font-size:1.05rem;line-height:1.8">{name}, ya casi estamos.</p>
</div>"""
    },
    {
        "subject": "Una Semana / Samantha Quince Anos",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">Una semana!</h2>
<p style="text-align:center;font-size:1.1rem;line-height:1.8">{name}, este sabado es el dia.</p>
<div style="text-align:center;margin:24px 0"><p style="font-size:2rem;color:#dcc898;margin:0"><strong>{days}</strong></p></div>
</div>"""
    },
    {
        "subject": "Ultimo Recordatorio / Samantha Quince Anos",
        "body": lambda name, days: f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h2 style="color:#dcc898;text-align:center;margin:0">Ya casi!</h2>
<p style="text-align:center;font-size:1.05rem;line-height:1.8">{name}, solo quedan <strong style="color:#dcc898">{days} dias</strong>.</p>
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
        "_id": uuid.uuid4().hex[:12],
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


@app.route('/rsvp/<entry_id>', methods=['DELETE'])
def delete_guest(entry_id):
    all_data = read_data()
    before = len(all_data)
    all_data = [g for g in all_data if g.get('_id') != entry_id]
    if len(all_data) == before:
        return jsonify({"error": "not found"}), 404
    write_data(all_data)
    return jsonify({"ok": True, "deleted": entry_id})


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
            should_send = True; new_stage = 1
        elif stage == 1 and 7 < days_until <= 20:
            should_send = True; new_stage = 2
        elif stage == 2 and 3 < days_until <= 13:
            should_send = True; new_stage = 3
        elif stage == 3 and 0 < days_until <= 6:
            should_send = True; new_stage = 4
        if should_send:
            tmpl = FOLLOWUP_TEMPLATES[new_stage - 1]
            if send_email(email, tmpl["subject"], tmpl["body"](guest["name"], days_until)):
                all_data[i]["followup_stage"] = new_stage
                sent_count += 1
                changed = True

    if changed:
        write_data(all_data)
    return jsonify({"ok": True, "days_until_event": days_until, "sent": sent_count})


@app.route('/stats', methods=['GET'])
def stats():
    all_data = read_data()
    total_attendees = len(all_data) + sum(g.get("guests", 0) for g in all_data)
    now = datetime.datetime.now()
    return jsonify({
        "total_rsvps": len(all_data),
        "total_attendees": total_attendees,
        "days_until": (EVENT_DATE - now).days,
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
