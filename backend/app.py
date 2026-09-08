from flask import Flask, request, jsonify
from flask_cors import CORS
import os, datetime, json, base64, smtplib, uuid, hmac
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests as req

app = Flask(__name__)

# The site is served from exactly one origin (GitHub Pages, no custom domain).
# A wide-open CORS(app) let ANY page on the internet call this API from a
# visitor's browser - including DELETE, whose _ids are public in rsvp_data.json.
ALLOWED_ORIGINS = [
    "https://cryptorich.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
CORS(app, origins=ALLOWED_ORIGINS)

# Deleting a guest is destructive and irreversible. It now requires a secret.
# Unset => every delete is refused (fail closed). Losing a guest costs more
# than an admin having to paste a key.
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")


def _admin_ok():
    supplied = request.headers.get("X-Admin-Key", "") or request.args.get("key", "")
    return bool(ADMIN_KEY) and hmac.compare_digest(supplied, ADMIN_KEY)


# Nothing a guest types is trusted for length or type. Unbounded strings go
# straight into a JSON file that is re-read and re-written on every RSVP.
FIELD_LIMITS = {"name": 120, "phone": 40, "email": 140, "address": 250, "message": 1200}
MAX_GUESTS = 10          # matches max="10" on the form


def _clean(data, key):
    v = data.get(key)
    return ("" if v is None else str(v)).strip()[:FIELD_LIMITS[key]]


def _clean_guests(v):
    """int('abc') used to raise straight through Flask as a 500."""
    try:
        n = int(float(str(v).strip() or 0))
    except (TypeError, ValueError):
        n = 0
    return max(0, min(MAX_GUESTS, n))

# ── GitHub API config ──────────────────────────────────────
def _load_gh_token():
    t = os.environ.get("GITHUB_TOKEN", "")
    if t:
        return t
    # The old fallback read backend/.ghtoken - a token COMMITTED TO THIS
    # PUBLIC REPO (reversed, to slip past GitHub secret scanning). It died
    # 2026-08-21 with 401 Bad credentials and took 13 days of RSVPs with it.
    # Secrets live in the Render environment only.
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

# Where the "you have a new guest" alert goes. Set HOST_EMAIL in the Render
# dashboard to change it without a redeploy; falls back to the sending account.
HOST_EMAIL = os.environ.get("HOST_EMAIL", "") or SMTP_USER
DASHBOARD_URL = os.environ.get(
    "DASHBOARD_URL", "https://cryptorich.github.io/samantha/rsvp/")

# ── Time ───────────────────────────────────────────────────
# TIMESTAMP BUG, fixed 2026-08-15. RSVPs were stored with
# datetime.utcnow().isoformat(), which yields "2026-08-14T22:38:06" with NO
# timezone marker. JavaScript parses an offset-less datetime as LOCAL time, so
# the dashboard rendered every RSVP 4 hours late, and anything after 8pm ET
# landed on the following day (Biby Santiago replied Fri 8:54pm, displayed Sat).
# Timestamps are now written timezone-aware (...+00:00). Existing rows stay
# exactly as they are and are read as UTC by the dashboard.
try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:                                  # pragma: no cover
    EASTERN = datetime.timezone(datetime.timedelta(hours=-4))  # EDT fallback


def now_utc():
    """Timezone-aware UTC. Never datetime.utcnow() — that returns a naive value
    that silently reads as local time everywhere downstream."""
    return datetime.datetime.now(datetime.timezone.utc)


EVENT_DATE = datetime.datetime(2026, 10, 3, 15, 0, 0, tzinfo=EASTERN)
EVENT = {
    "date_str": "Sabado 3 de Octubre 2026 / Saturday, October 3, 2026",
    "time": "3:00 PM - 6:00 PM",
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
class PersistError(Exception):
    """Storage is unreachable. NEVER swallow this — a guest must be told."""


# ── DATA-LOSS POSTMORTEM 2026-09-03 ────────────────────────
# The GitHub token died 2026-08-21 (401 Bad credentials). From that moment:
#   read_data()  -> GitHub 401 -> data = []  (silently "no guests")
#   submit()     -> [].append(guest) -> write_data([guest])
#   _write_internal -> PUT the 1-element array over the 14-record file
# Only the token being dead for WRITES too kept the 14 alive. A fresh token
# dropped into the old code would have wiped them on the next RSVP.
# Three invariants now hold:
#   1. A failed read RAISES. It never degrades into an empty list.
#   2. Every write MERGES into a fresh remote read, keyed by _id, so a stale
#      or empty in-memory list can only ever ADD, never remove.
#   3. A write that would shrink the file is refused unless it is an
#      explicit delete (allow_shrink=True).
def _gh_headers():
    return {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_read():
    """(data, sha) from GitHub. Raises PersistError — never returns []-on-error."""
    if not GH_TOKEN:
        raise PersistError(
            "GITHUB_TOKEN is not set. Refusing to serve or store RSVPs from "
            "ephemeral disk, which is wiped on every deploy."
        )
    try:
        r = req.get(GH_API, headers=_gh_headers(), timeout=15)
    except Exception as e:
        raise PersistError(f"GitHub unreachable: {e}")
    if r.status_code == 401:
        raise PersistError("GitHub token rejected (401). Rotate GITHUB_TOKEN in Render.")
    if r.status_code == 404:
        return [], ""            # file not created yet — legitimate empty
    if r.status_code != 200:
        raise PersistError(f"GitHub read failed: HTTP {r.status_code}")
    body = r.json()
    content = base64.b64decode(body["content"]).decode("utf-8")
    return json.loads(content), body.get("sha", "")


def read_data():
    data, _sha = _gh_read()
    changed = False
    for entry in data:
        if '_id' not in entry:
            entry['_id'] = uuid.uuid4().hex[:12]
            changed = True
    if changed:
        _write_internal(data)
    return data


def _write_internal(data, allow_shrink=False):
    """Merge `data` into the live remote file and PUT the union.

    allow_shrink=True is ONLY for the delete endpoint, which passes the full
    intended list.
    """
    remote, sha = _gh_read()

    if allow_shrink:
        merged = list(data)
    else:
        by_id = {}
        for e in remote:
            # A legacy row with no _id must NOT fall out of the merge. Adding a
            # newcomer in the same write keeps the count equal, so the length
            # guard below would not catch the loss. Give it an id and keep it.
            if not e.get('_id'):
                e['_id'] = uuid.uuid4().hex[:12]
            by_id[e['_id']] = e
        for e in data:
            if not e.get('_id'):
                e['_id'] = uuid.uuid4().hex[:12]
            by_id[e['_id']] = e              # update in place or append
        merged = list(by_id.values())
        merged.sort(key=lambda e: str(e.get('date') or ''))
        if len(merged) < len(remote):
            raise PersistError(
                f"refusing to shrink RSVP file {len(remote)} -> {len(merged)}"
            )

    content = json.dumps(merged, ensure_ascii=False, indent=2)
    payload = {
        "message": f"RSVP update ({len(merged)} guests)",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    try:
        r = req.put(GH_API, headers=_gh_headers(), json=payload, timeout=20)
    except Exception as e:
        raise PersistError(f"GitHub write unreachable: {e}")
    if r.status_code == 409:
        raise PersistError("GitHub write conflict (concurrent RSVP) — retry")
    if r.status_code not in (200, 201):
        raise PersistError(f"GitHub write failed: HTTP {r.status_code}")
    print(f"[data] Saved {len(merged)} RSVPs to GitHub")

    try:                                     # local mirror is a convenience only
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception:
        pass
    return merged


def write_data(data, allow_shrink=False):
    return _write_internal(data, allow_shrink=allow_shrink)


# ── Email Templates ────────────────────────────────────────
def confirmation_email(name):
    days = (EVENT_DATE - datetime.datetime.now(EASTERN)).days
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


def host_alert_email(entry, total_rsvps, total_guests):
    """Notify the host the moment someone RSVPs.

    Sent to HOST_EMAIL, separate from the guest's own confirmation. Every field
    the guest submitted is included so the host does not have to open the
    dashboard to know who replied - the dashboard link is for the full list.
    """
    name = entry.get("name") or "Someone"
    # Stated in Eastern with the zone spelled out. The stored value is UTC, and
    # reading it as anything else is exactly what made the dashboard confusing.
    try:
        _d = datetime.datetime.fromisoformat(entry["date"])
        # A stored value with no offset is UTC. It must be tagged explicitly:
        # astimezone() on a naive datetime assumes the SERVER's local zone,
        # which is right on Render only by accident and wrong anywhere else.
        if _d.tzinfo is None:
            _d = _d.replace(tzinfo=datetime.timezone.utc)
        received = _d.astimezone(EASTERN).strftime("%a %b %d, %Y at %I:%M %p %Z")
    except Exception:
        received = "-"
    rows = [
        ("Name", entry.get("name") or "-"),
        ("Guests", str(entry.get("guests", 0))),
        ("Phone", entry.get("phone") or "-"),
        ("Email", entry.get("email") or "-"),
        ("Address", entry.get("address") or "-"),
        ("Message", entry.get("message") or "-"),
        ("Received", received),
    ]
    cells = "".join(
        f"""<tr>
<td style="padding:9px 14px;border-bottom:1px solid rgba(196,160,74,0.12);color:rgba(236,228,212,0.55);font-size:0.78rem;letter-spacing:0.12em;text-transform:uppercase;white-space:nowrap;vertical-align:top">{k}</td>
<td style="padding:9px 14px;border-bottom:1px solid rgba(196,160,74,0.12);color:#ece4d4;font-size:1rem">{v}</td>
</tr>""" for k, v in rows)

    return (
        f"New RSVP: {name} (+{entry.get('guests', 0)}) - Samantha Quince Anos",
        f"""<div style="max-width:560px;margin:0 auto;font-family:Georgia,serif;color:#ece4d4;background:#0a0c09;padding:40px 32px;border:1px solid rgba(196,160,74,0.15);border-radius:12px">
<h1 style="color:#dcc898;font-size:1.6rem;text-align:center;margin:0 0 4px">You have a new Guest on your RSVP list</h1>
<p style="text-align:center;color:rgba(236,228,212,0.5);font-size:0.8rem;margin:0 0 26px">Tienes un nuevo invitado confirmado</p>
<table style="width:100%;border-collapse:collapse;background:rgba(6,8,5,0.6);border:1px solid rgba(196,160,74,0.12);border-radius:10px;overflow:hidden">{cells}</table>
<div style="text-align:center;margin:26px 0 8px">
<p style="margin:0 0 4px;font-size:1.3rem;color:#dcc898"><strong>{total_guests}</strong> guests across <strong>{total_rsvps}</strong> RSVPs</p>
<p style="margin:0;color:rgba(236,228,212,0.45);font-size:0.85rem">{EVENT['date_str']}<br>{EVENT['time']} - {EVENT['venue']}</p>
</div>
<div style="text-align:center;margin-top:28px">
<a href="{DASHBOARD_URL}" style="display:inline-block;padding:15px 34px;background:#b8942f;color:#0a0c09;text-decoration:none;border-radius:8px;font-family:Helvetica,Arial,sans-serif;font-size:0.72rem;letter-spacing:0.28em;text-transform:uppercase;font-weight:bold">View Full Guest List</a>
<p style="margin:14px 0 0;color:rgba(236,228,212,0.35);font-size:0.75rem">{DASHBOARD_URL}</p>
</div>
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
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid payload"}), 400
    name = _clean(data, 'name')
    if not name:
        return jsonify({"error": "name required"}), 400

    # The browser queues an RSVP whose response never arrived and resends it on
    # the next visit. Without a stable token the server writes the guest twice.
    # A token is NOT an _id: it can never overwrite another guest's row.
    client_token = str(data.get('client_token') or '').strip()[:64]

    entry = {
        "_id": uuid.uuid4().hex[:12],
        "name": name,
        "phone": _clean(data, 'phone'),
        "email": _clean(data, 'email'),
        "address": _clean(data, 'address'),
        "guests": _clean_guests(data.get('guests')),
        "message": _clean(data, 'message'),
        "client_token": client_token,
        "date": now_utc().isoformat(),   # tz-aware: ...+00:00
        "confirmation_sent": False,
        "followup_stage": 0,
    }

    # A guest is told "confirmed" ONLY after the RSVP is on GitHub. Before
    # 2026-09-03 this returned ok:true even when nothing was stored.
    try:
        all_data = read_data()
        if client_token:
            for g in all_data:
                if g.get("client_token") == client_token:
                    print(f"[submit] duplicate resend ignored for {name!r}")
                    return jsonify({
                        "ok": True, "duplicate": True,
                        "confirmation_sent": bool(g.get("confirmation_sent")),
                        "host_notified": False, "event": EVENT,
                    })
        all_data.append(entry)
        all_data = write_data(all_data)
    except PersistError as e:
        print(f"[submit] PERSIST FAILED — {name!r} not stored: {e}")
        return jsonify({
            "ok": False,
            "error": "storage_unavailable",
            "message": "No pudimos guardar tu RSVP / We could not save your RSVP.",
        }), 503

    if entry["email"]:
        subject, body = confirmation_email(name)
        if send_email(entry["email"], subject, body):
            entry["confirmation_sent"] = True
            try:
                write_data([entry])      # merge-by-_id: flips the flag only
            except PersistError as e:
                print(f"[submit] confirmation flag not persisted: {e}")

    # Host alert. Deliberately AFTER write_data and wrapped: the guest's RSVP is
    # already saved by this point, so a mail outage can never cost a response.
    host_notified = False
    try:
        if HOST_EMAIL:
            total_guests = len(all_data) + sum(int(g.get("guests") or 0) for g in all_data)
            subject, body = host_alert_email(entry, len(all_data), total_guests)
            host_notified = send_email(HOST_EMAIL, subject, body)
    except Exception as e:
        print(f"[host-alert] Failed: {e}")

    return jsonify({
        "ok": True,
        "confirmation_sent": entry["confirmation_sent"],
        "host_notified": host_notified,
        "event": EVENT,
    })


@app.route('/rsvp', methods=['GET'])
def list_guests():
    # Show "unavailable", never a falsely-empty guest list.
    try:
        return jsonify(read_data())
    except PersistError as e:
        return jsonify({"error": "storage_unavailable", "detail": str(e)}), 503


@app.route('/rsvp/<entry_id>', methods=['DELETE'])
def delete_guest(entry_id):
    if not _admin_ok():
        return jsonify({
            "error": "forbidden",
            "detail": "Deleting requires ADMIN_KEY. Set it in the Render "
                      "environment, then enter it on the guest-list page.",
        }), 403
    try:
        all_data = read_data()
        before = len(all_data)
        all_data = [g for g in all_data if g.get('_id') != entry_id]
        if len(all_data) == before:
            return jsonify({"error": "not found"}), 404
        write_data(all_data, allow_shrink=True)   # the one legitimate shrink
    except PersistError as e:
        return jsonify({"error": "storage_unavailable", "detail": str(e)}), 503
    return jsonify({"ok": True, "deleted": entry_id})


@app.route('/cron/send-followups', methods=['GET', 'POST'])
def send_followups():
    now = datetime.datetime.now(EASTERN)
    days_until = (EVENT_DATE - now).days
    if days_until <= 0:
        return jsonify({"ok": True, "message": "Event has passed", "sent": 0})

    try:
        all_data = read_data()
    except PersistError as e:
        return jsonify({"error": "storage_unavailable", "detail": str(e)}), 503
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
        try:
            write_data(all_data)
        except PersistError as e:
            print(f"[followups] flags not persisted: {e}")
    return jsonify({"ok": True, "days_until_event": days_until, "sent": sent_count})


@app.route('/stats', methods=['GET'])
def stats():
    try:
        all_data = read_data()
    except PersistError as e:
        return jsonify({"error": "storage_unavailable", "detail": str(e)}), 503
    total_attendees = len(all_data) + sum(g.get("guests", 0) for g in all_data)
    now = datetime.datetime.now(EASTERN)
    return jsonify({
        "total_rsvps": len(all_data),
        "total_attendees": total_attendees,
        "days_until": (EVENT_DATE - now).days,
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
