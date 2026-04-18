"""Thin application entry point — wires together all blueprints."""
import os
from datetime import datetime
from flask import Flask, session

# ── Graceful optional imports ───────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    HAS_LIMITER = True
except ImportError:
    HAS_LIMITER = False

try:
    from flask_session import Session as _FlaskSession
    HAS_FLASK_SESSION = True
except ImportError:
    HAS_FLASK_SESSION = False

try:
    from flask_wtf.csrf import CSRFProtect as _CSRFProtect, generate_csrf
    HAS_CSRF = True
except ImportError:
    HAS_CSRF = False

import importlib.util as _importlib_util
HAS_ANTHROPIC = _importlib_util.find_spec("anthropic") is not None

# ── App factory ─────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ptit_lost_found_please_change_this")

# ── Config ──────────────────────────────────────────────────────────────────
from config import UPLOAD_FOLDER, SESSION_DIR

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["SESSION_TYPE"]     = "filesystem"
app.config["SESSION_FILE_DIR"] = SESSION_DIR
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True

# ── Extensions ──────────────────────────────────────────────────────────────
if HAS_FLASK_SESSION:
    _FlaskSession(app)

if HAS_CSRF:
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600
    _CSRFProtect(app)

    @app.context_processor
    def _inject_csrf():
        return {"csrf_token": generate_csrf}

if HAS_LIMITER:
    _limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=[],
        storage_uri="memory://"
    )
    def _rate(s):
        return _limiter.limit(s)
else:
    def _rate(_s):
        def decorator(f):
            return f
        return decorator

# ── Jinja filter & global context ───────────────────────────────────────────
from utils import time_ago as _time_ago
from database import connect_db
from settings_utils import get_setting as _get_setting

app.add_template_filter(_time_ago, "time_ago")


@app.context_processor
def _inject_site_settings():
    return {
        "site_bank_name":    _get_setting("bank_name",    "MB Bank"),
        "site_bank_account": _get_setting("bank_account", "0359090502"),
        "site_bank_owner":   _get_setting("bank_owner",   "MAI XUAN TRUONG"),
        "site_phone":        _get_setting("contact_phone", "0359090502"),
        "site_email":        _get_setting("contact_email", "mxtxuantruong2805@gmail.com"),
        "site_address":      _get_setting("contact_address", "PTIT - Hà Nội"),
    }


@app.context_processor
def inject_globals():
    pending_claims_count = 0
    pending_claims_list  = []
    unread_chat_count    = 0
    unread_notif_count   = 0
    notif_list           = []
    if session.get("user_id") and "avatar" not in session:
        try:
            _row = connect_db().execute(
                "SELECT avatar FROM users WHERE id=?", (session["user_id"],)
            ).fetchone()
            session["avatar"] = (_row["avatar"] or "") if _row else ""
        except Exception:
            session["avatar"] = ""

    if session.get("user_id"):
        try:
            conn = connect_db()
            pending_claims_count = conn.execute("""
                SELECT COUNT(*) as cnt FROM claims c
                JOIN posts p ON c.found_post_id = p.id
                WHERE p.user_id = ? AND c.status IN ('pending','matched')
                  AND (c.owner_reviewed_at IS NULL)
            """, (session["user_id"],)).fetchone()["cnt"]
            pending_claims_list = conn.execute("""
                SELECT c.id, c.claim_description, c.ai_score, c.status, c.created_at,
                       u.full_name as claimer_name,
                       p.title as found_title, p.id as found_post_id
                FROM claims c
                JOIN posts p ON c.found_post_id = p.id
                JOIN users u ON c.claimer_user_id = u.id
                WHERE p.user_id = ? AND c.status IN ('pending','matched')
                  AND (c.owner_reviewed_at IS NULL)
                ORDER BY c.id DESC LIMIT 5
            """, (session["user_id"],)).fetchall()
            unread_chat_count = conn.execute("""
                SELECT COUNT(*) as cnt FROM chat_messages m
                JOIN claims c ON m.claim_id = c.id
                JOIN posts fp ON c.found_post_id = fp.id
                WHERE m.is_read = 0
                  AND m.sender_id != ?
                  AND (c.claimer_user_id = ? OR fp.user_id = ?)
            """, (session["user_id"], session["user_id"], session["user_id"])).fetchone()["cnt"]
            unread_notif_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM notifications WHERE user_id=? AND is_read=0",
                (session["user_id"],)
            ).fetchone()["cnt"]
            notif_list = conn.execute(
                "SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 10",
                (session["user_id"],)
            ).fetchall()
            conn.close()
        except Exception:
            pass

    active_announcement = None
    try:
        conn_ann = connect_db()
        now_str = str(datetime.now())
        active_announcement = conn_ann.execute("""
            SELECT * FROM announcements
            WHERE is_active=1
            AND (show_from IS NULL OR show_from <= ?)
            AND (show_until IS NULL OR show_until >= ?)
            ORDER BY id DESC LIMIT 1
        """, (now_str, now_str)).fetchone()
        conn_ann.close()
    except Exception:
        pass

    admin_pending_posts = admin_pending_payments = admin_pending_claims_count = admin_pending_reports = 0
    if session.get("role") in ("admin", "moderator"):
        try:
            conn_adm = connect_db()
            admin_pending_posts = conn_adm.execute(
                "SELECT COUNT(*) as c FROM posts WHERE status='pending_review'"
            ).fetchone()["c"]
            admin_pending_payments = conn_adm.execute(
                "SELECT COUNT(*) as c FROM payments WHERE status='pending'"
            ).fetchone()["c"]
            admin_pending_claims_count = conn_adm.execute(
                "SELECT COUNT(*) as c FROM claims WHERE status='pending'"
            ).fetchone()["c"]
            admin_pending_reports = conn_adm.execute(
                "SELECT COUNT(*) as c FROM reports WHERE status='pending'"
            ).fetchone()["c"]
            conn_adm.close()
        except Exception:
            pass

    return {
        "pending_claims_count": pending_claims_count,
        "pending_claims_list":  pending_claims_list,
        "unread_chat_count":    unread_chat_count,
        "unread_notif_count":   unread_notif_count,
        "notif_list":           notif_list,
        "ai_enabled": HAS_ANTHROPIC and bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
        "active_announcement":         active_announcement,
        "admin_pending_posts":         admin_pending_posts,
        "admin_pending_payments":      admin_pending_payments,
        "admin_pending_claims_count":  admin_pending_claims_count,
        "admin_pending_reports":       admin_pending_reports,
    }

@app.route("/notifications/mark-read", methods=["POST"])
def notifications_mark_read():
    if session.get("user_id"):
        conn = connect_db()
        conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],))
        conn.commit()
        conn.close()
    from flask import jsonify
    return jsonify({"ok": True})


# ── Database bootstrap ───────────────────────────────────────────────────────
from database import create_tables
create_tables()

# ── Register all blueprints ──────────────────────────────────────────────────
from blueprints import auth, home, profile, posts, search, claims, chat, payment, api, admin as admin_bp

for module in (auth, home, profile, posts, search, claims, chat, payment, api, admin_bp):
    module.register_routes(app, _rate)

# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, host="127.0.0.1", port=5000)
