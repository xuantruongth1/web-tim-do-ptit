from flask import Flask, render_template, request, redirect, session, flash, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
import os
import json
import shutil
import threading
import smtplib
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Graceful optional imports ──────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import anthropic as _anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    from PIL import Image as _PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

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

# ── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ptit_lost_found_please_change_this")

PER_PAGE = 12  # Số bài đăng mỗi trang

# ── Flask-Session (filesystem) ─────────────────────────────────────────────────
SESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flask_sessions")
os.makedirs(SESSION_DIR, exist_ok=True)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = SESSION_DIR
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True

# =========================
# GÓI VIP
# =========================
VIP_PACKAGES = {
    "goi_1": {"name": "Nổi bật",  "price": 10000,  "priority": 1, "label": "NỔI BẬT", "days": 3},
    "goi_2": {"name": "Ưu tiên",  "price": 20000,  "priority": 2, "label": "ƯU TIÊN", "days": 5},
    "goi_3": {"name": "Tìm gấp",  "price": 30000,  "priority": 3, "label": "TÌM GẤP", "days": 10},
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── Rate limiter ───────────────────────────────────────────────────────────────
if HAS_FLASK_SESSION:
    _FlaskSession(app)

if HAS_CSRF:
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600
    _csrf = _CSRFProtect(app)

    @app.context_processor
    def _inject_csrf():
        return {"csrf_token": generate_csrf}

if HAS_LIMITER:
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=[],
        storage_uri="memory://"
    )

    def _rate(s):
        return limiter.limit(s)
else:
    def _rate(_s):  # no-op decorator nếu flask-limiter chưa được cài
        def decorator(f):
            return f
        return decorator

# =========================
# HÀM HỖ TRỢ
# =========================
import unicodedata
import secrets as _secrets

def normalize_vn(text: str) -> str:
    """Chuyển tiếng Việt có dấu → không dấu, viết thường. VD: 'Điện thoại' → 'dien thoai'"""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower()


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("norm_vn", 1, normalize_vn)
    return conn


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file):
    """Lưu ảnh upload (resize tối đa 800px) và trả về tên file."""
    if not file or file.filename == "":
        return ""
    if not allowed_file(file.filename):
        return ""
    filename = secure_filename(file.filename)
    name, ext = os.path.splitext(filename)
    # Chuẩn hóa về .jpg để tiết kiệm dung lượng (trừ gif giữ nguyên)
    save_ext = ext.lower() if ext.lower() == ".gif" else ".jpg"
    filename = f"{name}_{int(datetime.now().timestamp())}{save_ext}"
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if HAS_PIL and save_ext != ".gif":
        try:
            img = _PILImage.open(file.stream)
            img = img.convert("RGB")
            img.thumbnail((800, 800), _PILImage.LANCZOS)
            img.save(save_path, "JPEG", quality=85, optimize=True)
            return filename
        except Exception:
            file.stream.seek(0)
    file.save(save_path)
    return filename


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Bạn cần đăng nhập để sử dụng chức năng này.", "warning")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapper


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Bạn không có quyền truy cập trang quản trị.", "danger")
            return redirect(url_for("home"))
        return view_func(*args, **kwargs)
    return wrapper


# =========================
# EMAIL
# =========================
def send_email(to_email, subject, html_body):
    """Send email in background thread. Silently skips if MAIL_USERNAME not configured."""
    if not to_email:
        return
    mail_user = os.environ.get("MAIL_USERNAME", "").strip()
    mail_pass = os.environ.get("MAIL_PASSWORD", "").strip()
    if not mail_user or not mail_pass:
        return

    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[PTIT Lost & Found] {subject}"
            msg["From"] = os.environ.get("MAIL_FROM", mail_user)
            msg["To"] = to_email
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            server = smtplib.SMTP(
                os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
                int(os.environ.get("MAIL_PORT", 587))
            )
            server.starttls()
            server.login(mail_user, mail_pass)
            server.send_message(msg)
            server.quit()
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


# =========================
# CLAUDE AI
# =========================
def claude_analyze_claim(found_post, claim_description, lost_post=None):
    """Dùng Claude API để phân tích mức độ khớp của yêu cầu nhận đồ.
    Trả về (score: int|None, reason: str|None).
    Nếu AI không khả dụng trả về (None, None) → dùng rule-based fallback.
    """
    if not HAS_ANTHROPIC:
        return None, None
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None, None

    lost_info = ""
    if lost_post:
        lost_info = (
            f"\n\nBài đăng mất đồ liên quan:\n"
            f"- Tiêu đề: {lost_post['title']}\n"
            f"- Mô tả: {(lost_post['description'] or 'Không có')[:300]}"
        )

    prompt = f"""Bạn là hệ thống xác minh thông minh cho website tìm đồ thất lạc PTIT Lost & Found.

Bài đăng đồ NHẶT ĐƯỢC:
- Tiêu đề: {found_post['title']}
- Danh mục: {found_post['category']}
- Mô tả: {(found_post['description'] or 'Không có')[:300]}
- Địa điểm: {found_post['location']}, {found_post.get('city', '') or ''}
- Gợi ý xác thực (công khai): {found_post.get('verification_hint', '') or 'Không có'}
{lost_info}

Người dùng khẳng định đây là đồ của họ và mô tả:
"{claim_description}"

Hãy phân tích xem người này có phải chủ thực sự không. Cho điểm từ 0-100:
- 80-100: Rõ ràng là chủ (chi tiết cụ thể, khớp chính xác)
- 60-79: Nhiều khả năng là chủ
- 40-59: Có thể, nên xem xét thêm
- 0-39: Không đủ bằng chứng

Chỉ trả về JSON, không có text khác: {{"score": <số 0-100>, "reason": "<1 câu lý do bằng tiếng Việt>"}}"""

    try:
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or None
        client = _anthropic.Anthropic(api_key=api_key, base_url=base_url) if base_url else _anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system="Bạn là hệ thống phân tích xác minh. Chỉ trả về JSON thuần túy.",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        # Tách JSON nếu bị bọc trong ```
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        result = json.loads(raw)
        score = min(100, max(0, int(result.get("score", 0))))
        reason = str(result.get("reason", ""))
        return score, reason
    except Exception as e:
        print(f"[AI] claude_analyze_claim error: {type(e).__name__}: {e}")
        return None, None


def claude_analyze_image(image_path):
    """Phân tích ảnh vật phẩm bằng Claude Vision, trả về dict gợi ý hoặc None."""
    if not HAS_ANTHROPIC:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        with open(image_path, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(image_path)[1].lower().lstrip(".")
        media_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                      "png": "image/png", "gif": "image/gif"}.get(ext, "image/jpeg")
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or None
        client = _anthropic.Anthropic(api_key=api_key, base_url=base_url) if base_url else _anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64",
                                                  "media_type": media_type, "data": img_data}},
                    {"type": "text", "text": (
                        "Phân tích ảnh vật phẩm thất lạc này. Trả về JSON thuần túy:\n"
                        '{"category":"<CCCD/Thẻ SV | Ví/Túi | Chìa khóa | Điện thoại | Thẻ xe | '
                        'Laptop/Máy tính | Quần áo | Sách/Vở | Tai nghe | Khác>",'
                        '"post_type":"<lost hoặc found hoặc empty>",'
                        '"description_hint":"<1-2 câu mô tả bằng tiếng Việt>",'
                        '"keywords":"<2-3 từ khóa phân cách bởi dấu phẩy>"}'
                    )}
                ]
            }]
        )
        raw = response.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[AI] claude_analyze_image error: {type(e).__name__}: {e}")
        return None


def check_banned_words(conn, *texts):
    """Trả về từ cấm đầu tiên tìm thấy trong texts, hoặc None nếu không có."""
    try:
        words = [r["word"] for r in conn.execute("SELECT word FROM banned_words").fetchall()]
        if not words:
            return None
        combined = " ".join(t.lower() for t in texts if t)
        for w in words:
            if w and w in combined:
                return w
    except Exception:
        pass
    return None


# =========================
# KHỞI TẠO DATABASE
# =========================
def create_tables():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        created_at TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        event_date TEXT,
        location TEXT NOT NULL,
        city TEXT,
        campus TEXT,
        contact TEXT NOT NULL,
        image TEXT,
        post_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        priority INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        user_id INTEGER,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        package_key TEXT NOT NULL,
        package_name TEXT NOT NULL,
        amount INTEGER NOT NULL,
        transfer_content TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        confirmed_at TEXT,
        payment_proof TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(post_id) REFERENCES posts(id)
    )
    """)

    # Migration: add payment_proof column to existing databases
    try:
        cursor.execute("ALTER TABLE payments ADD COLUMN payment_proof TEXT")
    except Exception:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lost_post_id INTEGER,
        found_post_id INTEGER NOT NULL,
        claimer_user_id INTEGER NOT NULL,
        claim_description TEXT,
        ai_score INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        FOREIGN KEY(lost_post_id) REFERENCES posts(id),
        FOREIGN KEY(found_post_id) REFERENCES posts(id),
        FOREIGN KEY(claimer_user_id) REFERENCES users(id)
    )
    """)
    conn.commit()

    # Admin logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admin_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        admin_username TEXT NOT NULL,
        action TEXT NOT NULL,
        target_type TEXT,
        target_id INTEGER,
        detail TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(post_id) REFERENCES posts(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        claim_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(claim_id) REFERENCES claims(id),
        FOREIGN KEY(sender_id) REFERENCES users(id)
    )
    """)

    conn.commit()

    # Migration: thêm cột an toàn
    migrations = [
        "ALTER TABLE posts ADD COLUMN verification_hint TEXT",
        "ALTER TABLE posts ADD COLUMN private_verification_note TEXT",
        "ALTER TABLE posts ADD COLUMN package_key TEXT",
        "ALTER TABLE posts ADD COLUMN vip_started_at TEXT",
        "ALTER TABLE posts ADD COLUMN vip_expires_at TEXT",
        "ALTER TABLE claims ADD COLUMN owner_confirmed INTEGER DEFAULT 0",
        "ALTER TABLE claims ADD COLUMN contact_unlocked INTEGER DEFAULT 0",
        "ALTER TABLE claims ADD COLUMN owner_reviewed_at TEXT",
        "ALTER TABLE claims ADD COLUMN ai_reason TEXT",
        "ALTER TABLE users ADD COLUMN is_locked INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN email TEXT",
    ]
    for sql in migrations:
        try:
            cursor.execute(sql)
        except sqlite3.OperationalError:
            pass

    conn.commit()

    # New tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS site_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        icon TEXT DEFAULT '📦',
        sort_order INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT,
        type TEXT DEFAULT 'info',
        show_from TEXT,
        show_until TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        created_by INTEGER
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS banned_words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        reporter_user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        admin_note TEXT,
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewed_by INTEGER
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vouchers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        discount_type TEXT DEFAULT 'percent',
        discount_value INTEGER NOT NULL,
        max_uses INTEGER DEFAULT 0,
        used_count INTEGER DEFAULT 0,
        valid_from TEXT,
        valid_until TEXT,
        applicable_packages TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        note TEXT
    )
    """)
    conn.commit()

    # Indexes for performance
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_posts_type_status ON posts(post_type, status)",
        "CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status)",
        "CREATE INDEX IF NOT EXISTS idx_posts_user_id ON posts(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_comments_post_id ON comments(post_id)",
        "CREATE INDEX IF NOT EXISTS idx_claims_found_post ON claims(found_post_id)",
        "CREATE INDEX IF NOT EXISTS idx_claims_claimer ON claims(claimer_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_payments_post ON payments(post_id)",
        "CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)",
    ]:
        try:
            cursor.execute(idx_sql)
        except Exception:
            pass
    conn.commit()

    # New column migrations
    new_migrations = [
        "ALTER TABLE posts ADD COLUMN is_pinned INTEGER DEFAULT 0",
        "ALTER TABLE posts ADD COLUMN is_scam_warned INTEGER DEFAULT 0",
        "ALTER TABLE posts ADD COLUMN pin_expires_at TEXT",
        "ALTER TABLE posts ADD COLUMN label TEXT",
        "ALTER TABLE users ADD COLUMN force_password_change INTEGER DEFAULT 0",
        "ALTER TABLE payments ADD COLUMN refunded INTEGER DEFAULT 0",
        "ALTER TABLE payments ADD COLUMN refund_note TEXT",
        "ALTER TABLE payments ADD COLUMN confirmed_by TEXT",
        "ALTER TABLE posts ADD COLUMN tags TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN email_token TEXT",
    ]
    for sql in new_migrations:
        try:
            cursor.execute(sql)
        except sqlite3.OperationalError:
            pass
    conn.commit()

    # Seed default categories if empty
    cat_count = cursor.execute("SELECT COUNT(*) as c FROM categories").fetchone()["c"]
    if cat_count == 0:
        default_cats = [
            ("CCCD / Giấy tờ", "🪪", 1), ("Ví / Túi", "👜", 2),
            ("Điện thoại", "📱", 3), ("Laptop / Máy tính", "💻", 4),
            ("Chìa khóa", "🔑", 5), ("Thẻ xe", "🎫", 6),
            ("Tai nghe", "🎧", 7), ("Quần áo", "👕", 8),
            ("Sách / Vở", "📚", 9), ("Thú cưng", "🐾", 10),
            ("Đồ dùng cá nhân", "🎒", 11), ("Khác", "📦", 99),
        ]
        for name, icon, order in default_cats:
            try:
                cursor.execute("INSERT INTO categories (name, icon, sort_order, created_at) VALUES (?,?,?,?)",
                               (name, icon, order, str(datetime.now())))
            except Exception:
                pass
        conn.commit()

    # Tạo admin mặc định
    admin = cursor.execute("SELECT * FROM users WHERE username = ?", ("admin",)).fetchone()
    if not admin:
        cursor.execute("""
        INSERT INTO users (full_name, username, password, role, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (
            "Quản trị viên", "admin",
            generate_password_hash("admin123"),
            "admin", str(datetime.now())
        ))
        conn.commit()

    conn.close()


create_tables()


# =========================
# SETTINGS HELPERS
# =========================
def get_setting(key, default=""):
    conn = connect_db()
    row = conn.execute("SELECT value FROM site_settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = connect_db()
    conn.execute("INSERT OR REPLACE INTO site_settings (key, value, updated_at) VALUES (?, ?, ?)",
                 (key, value, str(datetime.now())))
    conn.commit()
    conn.close()


def get_all_settings():
    conn = connect_db()
    rows = conn.execute("SELECT key, value FROM site_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


# =========================
# MODERATOR DECORATOR
# =========================
def moderator_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if session.get("role") not in ("admin", "moderator"):
            flash("Bạn không có quyền truy cập.", "danger")
            return redirect(url_for("home"))
        return view_func(*args, **kwargs)
    return wrapper


# =========================
# ADMIN LOG HELPER
# =========================
def log_admin_action(conn, action, target_type=None, target_id=None, detail=None):
    try:
        conn.execute("""
            INSERT INTO admin_logs (admin_id, admin_username, action, target_type, target_id, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            session.get("user_id"), session.get("username", "admin"),
            action, target_type, target_id, detail, str(datetime.now())
        ))
    except Exception:
        pass


# =========================
# LOGIC PRIORITY HẾT HẠN
# =========================
def downgrade_expired_priorities():
    conn = connect_db()
    try:
        conn.execute("""
            UPDATE posts SET priority = 0, package_key = NULL
            WHERE priority > 0
            AND vip_expires_at IS NOT NULL
            AND vip_expires_at < datetime('now', 'localtime')
        """)
        conn.commit()
    except Exception:
        pass
    conn.close()


# =========================
# JINJA FILTERS & CONTEXT
# =========================
@app.template_filter('time_ago')
def time_ago(date_str):
    if not date_str:
        return 'Không rõ'
    try:
        dt = datetime.fromisoformat(str(date_str)[:19])
        delta = datetime.now() - dt
        total_seconds = int(delta.total_seconds())
        if total_seconds < 3600:
            mins = max(1, total_seconds // 60)
            return f'{mins} phút trước'
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            return f'{hours} giờ trước'
        else:
            days = delta.days
            return f'{days} ngày trước'
    except Exception:
        return str(date_str)[:10]


def get_vip_packages():
    """Load VIP packages từ DB settings nếu có, fallback về hardcoded."""
    packages = {}
    for key in ("goi_1", "goi_2", "goi_3"):
        name  = get_setting(f"vip_{key}_name")
        price = get_setting(f"vip_{key}_price")
        days  = get_setting(f"vip_{key}_days")
        pri   = get_setting(f"vip_{key}_priority")
        label = get_setting(f"vip_{key}_label")
        if name and price and days and pri:
            packages[key] = {
                "name": name, "price": int(price), "priority": int(pri),
                "label": label or name.upper(), "days": int(days),
            }
    if not packages:
        packages = VIP_PACKAGES
    return packages


@app.context_processor
def inject_globals():
    """Inject biến toàn cục vào mọi template."""
    pending_claims_count = 0
    pending_claims_list = []
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
            # Số tin nhắn chưa đọc trong chat
            unread_chat_count = conn.execute("""
                SELECT COUNT(*) as cnt FROM chat_messages m
                JOIN claims c ON m.claim_id = c.id
                JOIN posts fp ON c.found_post_id = fp.id
                WHERE m.is_read = 0
                  AND m.sender_id != ?
                  AND (c.claimer_user_id = ? OR fp.user_id = ?)
            """, (session["user_id"], session["user_id"], session["user_id"])).fetchone()["cnt"]
            conn.close()
        except Exception:
            unread_chat_count = 0
    else:
        unread_chat_count = 0
    # Active announcement banner
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

    # Admin badge counts
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
        "pending_claims_list": pending_claims_list,
        "unread_chat_count": unread_chat_count,
        "ai_enabled": HAS_ANTHROPIC and bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
        "active_announcement": active_announcement,
        "admin_pending_posts": admin_pending_posts,
        "admin_pending_payments": admin_pending_payments,
        "admin_pending_claims_count": admin_pending_claims_count,
        "admin_pending_reports": admin_pending_reports,
    }


# =========================
# ROUTE CHUNG
# =========================
@app.route("/")
def home():
    downgrade_expired_priorities()
    conn = connect_db()

    lost_count = conn.execute(
        "SELECT COUNT(*) AS total FROM posts WHERE post_type='lost' AND status='active'"
    ).fetchone()["total"]
    found_count = conn.execute(
        "SELECT COUNT(*) AS total FROM posts WHERE post_type='found' AND status='active'"
    ).fetchone()["total"]
    total_users = conn.execute(
        "SELECT COUNT(*) AS total FROM users"
    ).fetchone()["total"]
    resolved_count = conn.execute(
        "SELECT COUNT(*) AS total FROM posts WHERE status='resolved'"
    ).fetchone()["total"]

    urgent_posts = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.status='active' AND p.priority > 0
        ORDER BY p.priority DESC, p.id DESC LIMIT 6
    """).fetchall()

    latest_lost_posts = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.post_type='lost' AND p.status='active'
        ORDER BY p.id DESC LIMIT 6
    """).fetchall()

    latest_found_posts = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.post_type='found' AND p.status='active'
        ORDER BY p.id DESC LIMIT 8
    """).fetchall()

    resolved_posts = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.status='resolved'
        ORDER BY p.id DESC LIMIT 5
    """).fetchall()

    conn.close()
    return render_template(
        "home.html",
        lost_count=lost_count,
        found_count=found_count,
        total_users=total_users,
        resolved_count=resolved_count,
        urgent_posts=urgent_posts,
        latest_lost_posts=latest_lost_posts,
        latest_found_posts=latest_found_posts,
        resolved_posts=resolved_posts,
    )


@app.route("/pricing")
def pricing():
    return render_template("pricing.html", packages=VIP_PACKAGES)


@app.route("/ho-tro-du-an")
def support_project():
    return render_template("support.html")


@app.route("/payment/<package_key>", methods=["GET", "POST"])
@login_required
def payment(package_key):
    package = VIP_PACKAGES.get(package_key)
    if not package:
        flash("Gói dịch vụ không hợp lệ.", "danger")
        return redirect(url_for("pricing"))

    transfer_content = f'{session["username"]} {package_key.upper()}'

    if request.method == "POST":
        post_id = request.form.get("post_id")
        if not post_id:
            flash("Bạn cần chọn bài đăng để nâng cấp.", "warning")
            return redirect(url_for("my_posts"))

        conn = connect_db()
        post = conn.execute(
            "SELECT * FROM posts WHERE id=? AND user_id=?",
            (post_id, session["user_id"])
        ).fetchone()

        if not post:
            conn.close()
            flash("Không tìm thấy bài đăng hợp lệ.", "danger")
            return redirect(url_for("my_posts"))

        conn.execute("""
            INSERT INTO payments (user_id, post_id, package_key, package_name,
                amount, transfer_content, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session["user_id"], post_id, package_key, package["name"],
            package["price"], transfer_content, "pending", str(datetime.now())
        ))
        conn.commit()
        conn.close()
        flash("Đã tạo yêu cầu thanh toán. Vui lòng chuyển khoản đúng nội dung để admin xác nhận.", "success")
        return redirect(url_for("my_posts"))

    conn = connect_db()
    my_posts = conn.execute(
        "SELECT * FROM posts WHERE user_id=? ORDER BY id DESC",
        (session["user_id"],)
    ).fetchall()
    conn.close()

    return render_template(
        "payment.html",
        package=package, package_key=package_key,
        bank_name=get_setting("bank_name", "MB Bank"),
        account_number=get_setting("bank_account", "0359090502"),
        account_name=get_setting("bank_owner", "MAI XUAN TRUONG"),
        transfer_content=transfer_content, my_posts=my_posts,
    )


# =========================
# XÁC THỰC
# =========================
@app.route("/register", methods=["GET", "POST"])
@_rate("5 per minute")
def register():
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        email = request.form.get("email", "").strip().lower() or None

        if len(password) < 6:
            flash("Mật khẩu phải có ít nhất 6 ký tự.", "danger")
            return redirect(url_for("register"))

        conn = connect_db()
        existing = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            conn.close()
            flash("Tên đăng nhập đã tồn tại.", "danger")
            return redirect(url_for("register"))

        email_token = _secrets.token_urlsafe(32) if email else None
        conn.execute("""
        INSERT INTO users (full_name, username, password, role, created_at, email, email_verified, email_token)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (full_name, username, generate_password_hash(password), "user",
              str(datetime.now()), email, 0, email_token))
        conn.commit()
        conn.close()
        # Gửi email xác minh nếu user có email
        if email and email_token:
            verify_url = request.host_url.rstrip("/") + url_for("verify_email", token=email_token)
            send_email(email, "Xác minh email — PTIT Lost & Found",
                f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;background:#f8fafc;border-radius:12px;">
                <h2 style="color:#16a34a;">Xác minh địa chỉ email</h2>
                <p>Xin chào <strong>{full_name}</strong>,</p>
                <p>Tài khoản <strong>@{username}</strong> đã được tạo. Nhấn nút bên dưới để xác minh email.</p>
                <a href="{verify_url}" style="display:inline-block;margin-top:12px;padding:10px 24px;background:#16a34a;color:white;border-radius:8px;text-decoration:none;font-weight:700;">Xác minh email →</a>
                <p style="margin-top:16px;font-size:12px;color:#94a3b8;">Nếu bạn không đăng ký, hãy bỏ qua email này.</p>
                </div>""")
        # Thông báo tới admin
        admin_email = os.environ.get("MAIL_USERNAME", "")
        if admin_email:
            send_email(admin_email, f"Người dùng mới đăng ký: @{username}",
                f"""<p>Người dùng mới vừa đăng ký:</p>
                <ul>
                  <li>Họ tên: <strong>{full_name}</strong></li>
                  <li>Username: <strong>@{username}</strong></li>
                  <li>Email: {email or 'Không có'}</li>
                  <li>Thời gian: {str(datetime.now())[:16]}</li>
                </ul>
                <a href="{request.host_url}admin/users">Quản lý người dùng →</a>""")
        if email:
            flash("Đăng ký thành công! Hãy kiểm tra email để xác minh tài khoản, sau đó đăng nhập.", "success")
        else:
            flash("Đăng ký thành công, hãy đăng nhập.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/verify-email/<token>")
def verify_email(token):
    conn = connect_db()
    user = conn.execute("SELECT id FROM users WHERE email_token=?", (token,)).fetchone()
    if not user:
        conn.close()
        flash("Link xác minh không hợp lệ hoặc đã được sử dụng.", "danger")
        return redirect(url_for("login"))
    conn.execute("UPDATE users SET email_verified=1, email_token=NULL WHERE id=?", (user["id"],))
    conn.commit()
    conn.close()
    flash("Email đã được xác minh thành công! Bạn có thể đăng nhập.", "success")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
@_rate("10 per minute")
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = connect_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()

        if not user or not check_password_hash(user["password"], password):
            flash("Sai tên đăng nhập hoặc mật khẩu.", "danger")
            return redirect(url_for("login"))

        if user["is_locked"]:
            flash("Tài khoản của bạn đã bị khóa. Vui lòng liên hệ admin.", "danger")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        session["full_name"] = user["full_name"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        flash("Đăng nhập thành công.", "success")
        if user["force_password_change"]:
            return redirect(url_for("change_password_forced"))
        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Bạn đã đăng xuất.", "info")
    return redirect(url_for("home"))


# =========================
# HỒ SƠ CÁ NHÂN
# =========================
@app.route("/profile")
@login_required
def profile():
    conn = connect_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    stats = {
        "total":        conn.execute("SELECT COUNT(*) as c FROM posts WHERE user_id=?", (session["user_id"],)).fetchone()["c"],
        "active":       conn.execute("SELECT COUNT(*) as c FROM posts WHERE user_id=? AND status='active'", (session["user_id"],)).fetchone()["c"],
        "resolved":     conn.execute("SELECT COUNT(*) as c FROM posts WHERE user_id=? AND status='resolved'", (session["user_id"],)).fetchone()["c"],
        "claims_sent":  conn.execute("SELECT COUNT(*) as c FROM claims WHERE claimer_user_id=?", (session["user_id"],)).fetchone()["c"],
    }
    conn.close()
    return render_template("profile.html", user=user, stats=stats)


# =========================
# QUẢN LÝ BÀI ĐĂNG
# =========================
@app.route("/create", methods=["GET", "POST"])
@login_required
def create_post():
    if request.method == "POST":
        title = request.form["title"].strip()
        category = request.form["category"].strip()
        description = request.form["description"].strip()
        event_date = request.form.get("event_date", "").strip()
        location = request.form["location"].strip()
        city = request.form.get("city", "").strip()
        campus = request.form.get("campus", "").strip()
        contact = request.form["contact"].strip()
        post_type = request.form["post_type"].strip()
        verification_hint = request.form.get("verification_hint", "").strip()
        private_verification_note = request.form.get("private_verification_note", "").strip()
        raw_tags = request.form.get("tags", "").strip()
        tags = ",".join(
            t.strip().lower()[:30] for t in raw_tags.split(",") if t.strip()
        )[:3 * 31]  # max 3 tags stored

        conn_bw = connect_db()
        banned = check_banned_words(conn_bw, title, description)
        conn_bw.close()
        if banned:
            flash(f"Nội dung chứa từ không được phép: «{banned}». Vui lòng chỉnh sửa lại.", "danger")
            return redirect(url_for("create_post"))

        if not verification_hint:
            flash("Vui lòng nhập Thông tin xác thực — đây là trường bắt buộc.", "danger")
            return redirect(url_for("create_post"))
        if not private_verification_note:
            flash("Vui lòng nhập Ghi chú riêng tư — đây là trường bắt buộc.", "danger")
            return redirect(url_for("create_post"))

        selected_package = request.form.get("selected_package", "free").strip()
        username = session.get("username", "")

        image_name = ""
        if "image" in request.files:
            image_name = save_uploaded_file(request.files["image"])

        if not image_name:
            sample_key = request.form.get("sample_image_key", "").strip()
            valid_samples = {"cccd", "wallet", "key", "phone", "student_card", "bag"}
            if sample_key in valid_samples:
                src = os.path.join(BASE_DIR, "static", "images", "samples", f"{sample_key}.svg")
                if os.path.exists(src):
                    dest_name = f"sample_{sample_key}_{int(datetime.now().timestamp())}.svg"
                    shutil.copy2(src, os.path.join(app.config["UPLOAD_FOLDER"], dest_name))
                    image_name = dest_name

        priority = 0
        package_key = None
        if selected_package in VIP_PACKAGES and post_type == "lost":
            priority = VIP_PACKAGES[selected_package]["priority"]
            package_key = selected_package

        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO posts (title, category, description, event_date, location, city, campus, contact,
            image, post_type, status, priority, created_at, user_id,
            verification_hint, private_verification_note, package_key, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            title, category, description, event_date, location, city, campus, contact,
            image_name, post_type, "pending_review", priority, str(datetime.now()),
            session["user_id"], verification_hint, private_verification_note, package_key, tags
        ))
        post_id = cursor.lastrowid

        if package_key:
            package = VIP_PACKAGES[package_key]
            transfer_content = f"LF-{post_id}-{package_key}-{username}"
            proof_name = save_uploaded_file(request.files.get("payment_proof"))
            conn.execute("""
                INSERT INTO payments (user_id, post_id, package_key, package_name,
                    amount, transfer_content, status, created_at, payment_proof)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session["user_id"], post_id, package_key, package["name"],
                package["price"], transfer_content, "pending", str(datetime.now()), proof_name
            ))

        conn.commit()
        conn.close()
        # Thông báo admin có bài mới chờ duyệt
        admin_email = os.environ.get("MAIL_USERNAME", "")
        if admin_email:
            send_email(admin_email, f"Bài đăng mới chờ duyệt #{post_id}",
                f"""<p>Có bài đăng mới cần duyệt:</p>
                <ul>
                  <li>ID: <strong>#{post_id}</strong></li>
                  <li>Tiêu đề: <strong>{title}</strong></li>
                  <li>Loại: {'Mất đồ' if post_type == 'lost' else 'Nhặt được'}</li>
                  <li>Gói: {package_key or 'Thường'}</li>
                  <li>Người đăng: @{session.get('username','')}</li>
                </ul>
                <a href="{request.host_url}admin/posts?status=pending_review" style="padding:8px 16px;background:#f59e0b;color:white;border-radius:6px;text-decoration:none;font-weight:700;">Duyệt ngay →</a>""")
        return redirect(url_for("post_success", post_id=post_id))

    return render_template("create_post.html", packages=VIP_PACKAGES)


@app.route("/edit/<int:post_id>", methods=["GET", "POST"])
@login_required
def edit_post(post_id):
    conn = connect_db()
    post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()

    if not post:
        conn.close()
        flash("Không tìm thấy bài đăng.", "danger")
        return redirect(url_for("my_posts"))

    if post["user_id"] != session["user_id"] and session.get("role") != "admin":
        conn.close()
        flash("Bạn không có quyền chỉnh sửa bài này.", "danger")
        return redirect(url_for("my_posts"))

    if request.method == "POST":
        title = request.form["title"].strip()
        category = request.form["category"].strip()
        description = request.form.get("description", "").strip()
        event_date = request.form.get("event_date", "").strip()
        location = request.form["location"].strip()
        city = request.form.get("city", "").strip()
        campus = request.form.get("campus", "").strip()
        contact = request.form["contact"].strip()
        verification_hint = request.form.get("verification_hint", "").strip()
        private_verification_note = request.form.get("private_verification_note", "").strip()
        raw_tags = request.form.get("tags", "").strip()
        tags = ",".join(
            t.strip().lower()[:30] for t in raw_tags.split(",") if t.strip()
        )[:3 * 31]

        image_name = post["image"]
        if "image" in request.files:
            new_img = save_uploaded_file(request.files["image"])
            if new_img:
                image_name = new_img

        conn.execute("""
            UPDATE posts SET title=?, category=?, description=?, event_date=?, location=?,
                city=?, campus=?, contact=?, image=?,
                verification_hint=?, private_verification_note=?, tags=?
            WHERE id=?
        """, (title, category, description, event_date, location, city, campus,
              contact, image_name, verification_hint, private_verification_note, tags, post_id))
        conn.commit()
        conn.close()
        flash("Đã cập nhật bài đăng thành công.", "success")
        return redirect(url_for("post_detail", post_id=post_id))

    conn.close()
    return render_template("edit_post.html", post=post)


@app.route("/post-success/<int:post_id>")
@login_required
def post_success(post_id):
    conn = connect_db()
    post = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id WHERE p.id=?
    """, (post_id,)).fetchone()
    conn.close()
    if not post or post["user_id"] != session["user_id"]:
        return redirect(url_for("home"))
    return render_template("post_success.html", post=post)


@app.route("/lost")
def lost_posts():
    downgrade_expired_priorities()
    page = request.args.get("page", 1, type=int)
    conn = connect_db()

    total = conn.execute(
        "SELECT COUNT(*) as c FROM posts WHERE post_type='lost' AND status='active'"
    ).fetchone()["c"]

    posts = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.post_type='lost' AND p.status='active'
        ORDER BY p.priority DESC, p.id DESC
        LIMIT ? OFFSET ?
    """, (PER_PAGE, (page - 1) * PER_PAGE)).fetchall()
    conn.close()

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return render_template(
        "posts.html", page_title="Tin mất & thất lạc", posts=posts,
        current_type="lost", page=page, total_pages=total_pages, total=total,
    )


@app.route("/found")
def found_posts():
    downgrade_expired_priorities()
    page = request.args.get("page", 1, type=int)
    conn = connect_db()

    total = conn.execute(
        "SELECT COUNT(*) as c FROM posts WHERE post_type='found' AND status='active'"
    ).fetchone()["c"]

    posts = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.post_type='found' AND p.status='active'
        ORDER BY p.priority DESC, p.id DESC
        LIMIT ? OFFSET ?
    """, (PER_PAGE, (page - 1) * PER_PAGE)).fetchall()
    conn.close()

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return render_template(
        "posts.html", page_title="Nhặt được & tìm thấy", posts=posts,
        current_type="found", page=page, total_pages=total_pages, total=total,
    )


@app.route("/premium")
def premium_posts():
    downgrade_expired_priorities()
    page = request.args.get("page", 1, type=int)
    conn = connect_db()

    total = conn.execute(
        "SELECT COUNT(*) as c FROM posts WHERE status='active' AND priority>0"
    ).fetchone()["c"]

    posts = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.status='active' AND p.priority>0
        ORDER BY p.priority DESC, p.id DESC
        LIMIT ? OFFSET ?
    """, (PER_PAGE, (page - 1) * PER_PAGE)).fetchall()
    conn.close()

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return render_template(
        "posts.html", page_title="Bài đăng trả phí", posts=posts,
        current_type="premium", page=page, total_pages=total_pages, total=total,
    )


@app.route("/api/quick-search")
def quick_search_api():
    from flask import jsonify
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    q_norm = normalize_vn(q)
    conn = connect_db()
    rows = conn.execute("""
        SELECT p.id, p.title, p.post_type, p.category, p.location, p.image,
               p.priority, p.created_at, u.full_name
        FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.status = 'active'
          AND (norm_vn(p.title) LIKE ? OR norm_vn(p.description) LIKE ? OR norm_vn(p.category) LIKE ?)
        ORDER BY p.priority DESC, p.id DESC
        LIMIT 12
    """, (f"%{q_norm}%", f"%{q_norm}%", f"%{q_norm}%")).fetchall()
    conn.close()
    results = []
    for r in rows:
        score = 0
        if q_norm in normalize_vn(r["title"] or ""):
            score += 60
        if q_norm in normalize_vn(r["category"] or ""):
            score += 30
        if q_norm in normalize_vn(r["location"] or ""):
            score += 20
        score = min(score + 10, 100)
        results.append({
            "id": r["id"],
            "title": r["title"],
            "post_type": r["post_type"],
            "category": r["category"] or "",
            "location": r["location"] or "",
            "image": r["image"] or "",
            "priority": r["priority"],
            "full_name": r["full_name"] or "",
            "score": score,
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(results)


@app.route("/search", methods=["GET", "POST"])
def search():
    downgrade_expired_priorities()
    page = request.args.get("page", 1, type=int)
    posts = []
    keyword = category = city = post_type = ""
    total = total_pages = 0

    if request.method == "POST":
        keyword  = request.form.get("keyword", "").strip()
        category = request.form.get("category", "").strip()
        city     = request.form.get("city", "").strip()
        post_type = request.form.get("post_type", "").strip()
        page = 1
    else:
        keyword  = request.args.get("keyword", "").strip()
        category = request.args.get("category", "").strip()
        city     = request.args.get("city", "").strip()
        post_type = request.args.get("post_type", "").strip()

    if keyword or category or city or post_type:
        base_query = """
            FROM posts p LEFT JOIN users u ON p.user_id = u.id
            WHERE p.status='active'
        """
        params = []
        if keyword:
            kw_norm = normalize_vn(keyword)
            base_query += " AND (norm_vn(p.title) LIKE ? OR norm_vn(p.description) LIKE ? OR norm_vn(p.location) LIKE ?)"
            params.extend([f"%{kw_norm}%", f"%{kw_norm}%", f"%{kw_norm}%"])
        if category:
            base_query += " AND p.category LIKE ?"
            params.append(f"%{category}%")
        if city:
            base_query += " AND p.city LIKE ?"
            params.append(f"%{city}%")
        if post_type:
            base_query += " AND p.post_type = ?"
            params.append(post_type)

        conn = connect_db()
        total = conn.execute(f"SELECT COUNT(*) as c {base_query}", params).fetchone()["c"]
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

        order_offset = " ORDER BY p.priority DESC, p.id DESC LIMIT ? OFFSET ?"
        posts = conn.execute(
            f"SELECT p.*, u.full_name {base_query}{order_offset}",
            params + [PER_PAGE, (page - 1) * PER_PAGE]
        ).fetchall()
        conn.close()

    return render_template(
        "search.html",
        posts=posts, keyword=keyword, category=category,
        city=city, post_type=post_type,
        page=page, total_pages=total_pages, total=total,
    )


# =========================
# MATCHING (RULE-BASED)
# =========================
def match_score(lost_post, found_post):
    """Chấm điểm rule-based (fallback khi không có Claude AI)."""
    score = 0
    lost_title    = (lost_post["title"] or "").lower()
    found_title   = (found_post["title"] or "").lower()
    lost_category = (lost_post["category"] or "").lower()
    found_category = (found_post["category"] or "").lower()
    lost_desc     = (lost_post["description"] or "").lower()
    found_desc    = (found_post["description"] or "").lower()
    lost_location = (lost_post["location"] or "").lower()
    found_location = (found_post["location"] or "").lower()
    lost_city     = (lost_post["city"] or "").lower()
    found_city    = (found_post["city"] or "").lower()

    if lost_title == found_title:
        score += 40
    elif lost_title and found_title and (lost_title in found_title or found_title in lost_title):
        score += 25
    if lost_category == found_category and lost_category:
        score += 20
    if lost_location == found_location and lost_location:
        score += 20
    if lost_city == found_city and lost_city:
        score += 10
    for word in lost_desc.split():
        if len(word) > 2 and word in found_desc:
            score += 5
    lost_tags  = set(t.strip() for t in (lost_post["tags"] or "" if "tags" in lost_post.keys() else "").split(",") if t.strip())
    found_tags = set(t.strip() for t in (found_post["tags"] or "" if "tags" in found_post.keys() else "").split(",") if t.strip())
    score += len(lost_tags & found_tags) * 5
    return min(score, 100)


@app.route("/match")
@login_required
def match():
    conn = connect_db()
    user_id = session["user_id"]
    is_admin = session.get("role") == "admin"

    lost_posts_all  = conn.execute("SELECT * FROM posts WHERE post_type='lost'  AND status='active'").fetchall()
    found_posts_all = conn.execute("SELECT * FROM posts WHERE post_type='found' AND status='active'").fetchall()
    conn.close()

    results = []
    for lost_item in lost_posts_all:
        for found_item in found_posts_all:
            # User thường chỉ thấy gợi ý có liên quan đến bài của mình
            if not is_admin and lost_item["user_id"] != user_id and found_item["user_id"] != user_id:
                continue
            score = match_score(lost_item, found_item)
            if score >= 30:
                results.append((lost_item, found_item, score))

    results.sort(key=lambda x: x[2], reverse=True)
    results = results[:30]

    return render_template("match.html", results=results, is_admin=is_admin)


@app.route("/post/<int:post_id>")
def post_detail(post_id):
    conn = connect_db()
    post = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id WHERE p.id=?
    """, (post_id,)).fetchone()

    if not post:
        conn.close()
        flash("Không tìm thấy bài đăng.", "danger")
        return redirect(url_for("home"))

    contact_unlocked = False
    my_lost_posts = []

    if post["post_type"] == "found":
        user_id = session.get("user_id")
        if user_id:
            if user_id == post["user_id"] or session.get("role") == "admin":
                contact_unlocked = True
            else:
                unlocked_claim = conn.execute("""
                    SELECT id FROM claims
                    WHERE found_post_id=? AND claimer_user_id=? AND contact_unlocked=1 LIMIT 1
                """, (post_id, user_id)).fetchone()
                contact_unlocked = unlocked_claim is not None

                my_lost_posts = conn.execute(
                    "SELECT * FROM posts WHERE user_id=? AND post_type='lost' ORDER BY id DESC",
                    (user_id,)
                ).fetchall()

    # Related posts: cùng danh mục, khác loại (lost ↔ found), tối đa 4 bài
    related_posts = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.category = ? AND p.id != ? AND p.status = 'active'
          AND p.post_type != ?
        ORDER BY p.priority DESC, p.id DESC LIMIT 4
    """, (post["category"], post_id, post["post_type"])).fetchall()

    # Nếu ít hơn 4, bổ sung thêm bài cùng thành phố
    if len(related_posts) < 4 and post["city"]:
        exclude_ids = [r["id"] for r in related_posts] or [0]
        placeholders = ",".join("?" * len(exclude_ids))
        extra = conn.execute(
            f"""SELECT p.*, u.full_name FROM posts p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE p.city = ? AND p.id != ? AND p.status = 'active'
              AND p.id NOT IN ({placeholders})
            ORDER BY p.priority DESC, p.id DESC LIMIT ?""",
            [post["city"], post_id] + exclude_ids + [4 - len(related_posts)]
        ).fetchall()
        related_posts = list(related_posts) + list(extra)

    comments = conn.execute("""
        SELECT c.*, u.full_name, u.username, u.role
        FROM comments c JOIN users u ON c.user_id = u.id
        WHERE c.post_id = ? ORDER BY c.id ASC
    """, (post_id,)).fetchall()

    # Chat: tìm claim đã được owner_confirmed của user hiện tại
    confirmed_claim_id = None
    if session.get("user_id") and post["post_type"] == "found":
        confirmed = conn.execute("""
            SELECT id FROM claims
            WHERE found_post_id=? AND claimer_user_id=? AND status='owner_confirmed' LIMIT 1
        """, (post_id, session["user_id"])).fetchone()
        if confirmed:
            confirmed_claim_id = confirmed["id"]

    # Reports
    approved_reports = conn.execute("""
        SELECT r.*, u.full_name as reporter_name FROM reports r
        LEFT JOIN users u ON r.reporter_user_id = u.id
        WHERE r.post_id = ? AND r.status = 'approved'
        ORDER BY r.id DESC
    """, (post_id,)).fetchall()
    user_already_reported = False
    if session.get("user_id"):
        user_already_reported = conn.execute(
            "SELECT id FROM reports WHERE post_id=? AND reporter_user_id=? AND status != 'rejected'",
            (post_id, session["user_id"])
        ).fetchone() is not None

    conn.close()
    return render_template("post_detail.html", post=post,
                           contact_unlocked=contact_unlocked,
                           my_lost_posts=my_lost_posts,
                           related_posts=related_posts,
                           comments=comments,
                           confirmed_claim_id=confirmed_claim_id,
                           approved_reports=approved_reports,
                           user_already_reported=user_already_reported)


# =========================
# BÌNH LUẬN
# =========================
@app.route("/post/<int:post_id>/comment", methods=["POST"])
@login_required
def add_comment(post_id):
    content = request.form.get("content", "").strip()
    if not content:
        flash("Nội dung bình luận không được để trống.", "warning")
        return redirect(url_for("post_detail", post_id=post_id))
    if len(content) > 1000:
        flash("Bình luận tối đa 1000 ký tự.", "warning")
        return redirect(url_for("post_detail", post_id=post_id))
    conn = connect_db()
    banned = check_banned_words(conn, content)
    if banned:
        conn.close()
        flash(f"Bình luận chứa từ không được phép: «{banned}».", "danger")
        return redirect(url_for("post_detail", post_id=post_id))
    post = conn.execute("SELECT p.*, u.email, u.full_name FROM posts p JOIN users u ON p.user_id=u.id WHERE p.id=?", (post_id,)).fetchone()
    conn.execute(
        "INSERT INTO comments (post_id, user_id, content, created_at) VALUES (?,?,?,?)",
        (post_id, session["user_id"], content, str(datetime.now()))
    )
    conn.commit()
    conn.close()
    if post and post["email"] and post["user_id"] != session["user_id"]:
        send_email(post["email"], f"Bình luận mới trên bài: {post['title'][:40]}",
            f"<p>Xin chào <strong>{post['full_name']}</strong>,</p>"
            f"<p><strong>{session.get('username','Ai đó')}</strong> vừa bình luận trên bài đăng của bạn.</p>"
            f"<blockquote style='border-left:3px solid #e2e8f0;padding:8px 12px;color:#374151'>{content[:200]}</blockquote>"
            f"<p><a href='{request.host_url}post/{post_id}#comments'>Xem bình luận →</a></p>")
    return redirect(url_for("post_detail", post_id=post_id) + "#comments")


@app.route("/comment/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(comment_id):
    conn = connect_db()
    comment = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
    if not comment:
        conn.close()
        flash("Không tìm thấy bình luận.", "danger")
        return redirect(url_for("home"))
    if comment["user_id"] != session["user_id"] and session.get("role") != "admin":
        conn.close()
        flash("Bạn không có quyền xóa bình luận này.", "danger")
        return redirect(url_for("home"))
    post_id = comment["post_id"]
    if session.get("role") == "admin":
        log_admin_action(conn, f"Xóa bình luận #{comment_id}", "comment", comment_id,
                         f"Post #{post_id}: {comment['content'][:60]}")
    conn.execute("DELETE FROM comments WHERE id=?", (comment_id,))
    conn.commit()
    conn.close()
    flash("Đã xóa bình luận.", "success")
    return redirect(url_for("post_detail", post_id=post_id) + "#comments")


@app.route("/comment/<int:comment_id>/edit", methods=["POST"])
@login_required
def edit_comment(comment_id):
    content = request.form.get("content", "").strip()
    if not content or len(content) > 1000:
        flash("Nội dung không hợp lệ.", "warning")
        return redirect(url_for("home"))
    conn = connect_db()
    comment = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
    if not comment:
        conn.close()
        flash("Không tìm thấy bình luận.", "danger")
        return redirect(url_for("home"))
    if comment["user_id"] != session["user_id"] and session.get("role") != "admin":
        conn.close()
        flash("Bạn không có quyền sửa bình luận này.", "danger")
        return redirect(url_for("home"))
    post_id = comment["post_id"]
    conn.execute("UPDATE comments SET content=? WHERE id=?", (content, comment_id))
    if session.get("role") == "admin":
        log_admin_action(conn, f"Sửa bình luận #{comment_id}", "comment", comment_id,
                         f"Post #{post_id}")
    conn.commit()
    conn.close()
    flash("Đã cập nhật bình luận.", "success")
    return redirect(url_for("post_detail", post_id=post_id) + "#comments")


# =========================
# BÁO CÁO (REPORT)
# =========================
@app.route("/post/<int:post_id>/report", methods=["POST"])
@login_required
def submit_report(post_id):
    conn = connect_db()
    post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        conn.close()
        flash("Không tìm thấy bài đăng.", "danger")
        return redirect(url_for("home"))

    if post["user_id"] == session["user_id"]:
        conn.close()
        flash("Bạn không thể báo cáo bài đăng của chính mình.", "warning")
        return redirect(url_for("post_detail", post_id=post_id))

    existing = conn.execute(
        "SELECT id FROM reports WHERE post_id=? AND reporter_user_id=? AND status != 'rejected'",
        (post_id, session["user_id"])
    ).fetchone()
    if existing:
        conn.close()
        flash("Bạn đã báo cáo bài đăng này rồi.", "warning")
        return redirect(url_for("post_detail", post_id=post_id))

    content = request.form.get("content", "").strip()
    if not content:
        conn.close()
        flash("Vui lòng nhập nội dung báo cáo.", "warning")
        return redirect(url_for("post_detail", post_id=post_id))
    if len(content) > 2000:
        conn.close()
        flash("Nội dung báo cáo tối đa 2000 ký tự.", "warning")
        return redirect(url_for("post_detail", post_id=post_id))

    conn.execute(
        "INSERT INTO reports (post_id, reporter_user_id, content, status, created_at) VALUES (?,?,?,'pending',?)",
        (post_id, session["user_id"], content, str(datetime.now()))
    )
    conn.commit()
    conn.close()
    flash("Báo cáo của bạn đã được gửi. Admin sẽ xem xét sớm nhất có thể.", "success")
    return redirect(url_for("post_detail", post_id=post_id))


# =========================
# CLAIMS / XÁC MINH
# =========================
@app.route("/claim/<int:found_post_id>", methods=["GET", "POST"])
@login_required
def claim_form(found_post_id):
    if request.method == "GET":
        flash("Để xác minh, vui lòng dùng nút \"Đây là đồ của tôi\" trực tiếp trên trang chi tiết bài.", "info")
        return redirect(url_for("post_detail", post_id=found_post_id))

    conn = connect_db()
    found_post = conn.execute(
        "SELECT * FROM posts WHERE id=? AND post_type='found'", (found_post_id,)
    ).fetchone()

    if not found_post:
        conn.close()
        flash("Không tìm thấy bài đăng nhặt đồ.", "danger")
        return redirect(url_for("home"))

    if found_post["user_id"] == session["user_id"]:
        conn.close()
        flash("Bạn không thể xác minh đồ do chính mình đăng.", "warning")
        return redirect(url_for("post_detail", post_id=found_post_id))

    claim_description = request.form.get("claim_description", "").strip()
    if not claim_description:
        conn.close()
        flash("Vui lòng nhập nội dung xác minh.", "danger")
        return redirect(url_for("post_detail", post_id=found_post_id))

    # ── Chống spam: 1 claim / user / bài / 1 giờ ─────────────────────────────
    existing = conn.execute("""
        SELECT created_at FROM claims
        WHERE found_post_id=? AND claimer_user_id=?
        ORDER BY id DESC LIMIT 1
    """, (found_post_id, session["user_id"])).fetchone()

    if existing:
        try:
            claim_dt = datetime.fromisoformat(existing["created_at"][:19])
            wait = timedelta(hours=1) - (datetime.now() - claim_dt)
            if wait.total_seconds() > 0:
                conn.close()
                mins = max(1, int(wait.total_seconds() / 60))
                flash(f"Bạn đã gửi xác minh cho bài này rồi. Vui lòng đợi thêm {mins} phút.", "warning")
                return redirect(url_for("post_detail", post_id=found_post_id))
        except Exception:
            pass

    lost_post_id = request.form.get("lost_post_id") or None
    lost_post = conn.execute("SELECT * FROM posts WHERE id=?", (lost_post_id,)).fetchone() if lost_post_id else None

    # ── Thử Claude AI trước ────────────────────────────────────────────────────
    ai_score, ai_reason = claude_analyze_claim(found_post, claim_description, lost_post)

    if ai_score is not None:
        final_score = ai_score
    else:
        # Fallback rule-based
        base_score = match_score(lost_post, found_post) if lost_post else 0
        words = claim_description.lower().split()
        found_desc  = (found_post["description"] or "").lower()
        found_hint  = (found_post.get("verification_hint") or "").lower()
        private_hint = (found_post.get("private_verification_note") or "").lower()
        match_word_count = sum(
            1 for w in words if len(w) > 3 and (w in found_desc or w in found_hint or w in private_hint)
        )
        final_score = min(100, base_score + match_word_count * 5)
        ai_reason = None

    status = "matched" if final_score >= 50 else "low_match"
    contact_unlocked_val = 1 if final_score >= 50 else 0

    conn.execute("""
        INSERT INTO claims (lost_post_id, found_post_id, claimer_user_id,
            claim_description, ai_score, status, created_at, contact_unlocked, ai_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (lost_post_id, found_post_id, session["user_id"],
          claim_description, final_score, status, str(datetime.now()),
          contact_unlocked_val, ai_reason))
    conn.commit()
    if final_score >= 50:
        found_owner = conn.execute(
            "SELECT email, full_name FROM users WHERE id=?", (found_post["user_id"],)
        ).fetchone()
        if found_owner and found_owner["email"]:
            send_email(found_owner["email"], "Có người khớp với đồ bạn đăng!",
                f"<p>Xin chào <strong>{found_owner['full_name']}</strong>,</p>"
                f"<p>Có người vừa xác minh với điểm <strong>{final_score}/100</strong> cho bài nhặt được của bạn: "
                f"<em>{found_post['title']}</em>.</p>"
                f"<p><a href='{request.host_url}my-received-claims'>Xem yêu cầu nhận đồ →</a></p>")
    conn.close()

    source = "AI" if ai_score is not None else "thuật toán"
    if final_score >= 50:
        flash(f"Điểm xác minh ({source}): {final_score}/100 — Thông tin liên hệ đã được mở khóa!", "success")
    else:
        flash(f"Điểm xác minh ({source}): {final_score}/100 — Chưa đủ điểm. Người nhặt được sẽ xem xét.", "warning")
    return redirect(url_for("post_detail", post_id=found_post_id))


@app.route("/my-claims")
@login_required
def my_claims():
    conn = connect_db()
    claims = conn.execute("""
        SELECT c.*, p.title as found_title
        FROM claims c LEFT JOIN posts p ON c.found_post_id = p.id
        WHERE c.claimer_user_id=? ORDER BY c.id DESC
    """, (session["user_id"],)).fetchall()
    conn.close()
    return render_template("my_claims.html", claims=claims)


@app.route("/my-posts")
@login_required
def my_posts():
    conn = connect_db()
    posts = conn.execute(
        "SELECT * FROM posts WHERE user_id=? ORDER BY id DESC",
        (session["user_id"],)
    ).fetchall()
    conn.close()
    return render_template("my_posts.html", posts=posts)


@app.route("/resolve/<int:post_id>")
@login_required
def resolve_post(post_id):
    conn = connect_db()
    post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        conn.close()
        flash("Không tìm thấy bài đăng.", "danger")
        return redirect(url_for("my_posts"))
    if post["user_id"] != session["user_id"] and session.get("role") != "admin":
        conn.close()
        flash("Bạn không có quyền cập nhật bài này.", "danger")
        return redirect(url_for("my_posts"))
    conn.execute("UPDATE posts SET status='resolved' WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    flash("Đã đánh dấu bài đăng là đã xử lý.", "success")
    return redirect(url_for("my_posts"))


@app.route("/delete/<int:post_id>")
@login_required
def delete_post(post_id):
    conn = connect_db()
    post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        conn.close()
        flash("Không tìm thấy bài đăng.", "danger")
        return redirect(url_for("my_posts"))
    if post["user_id"] != session["user_id"] and session.get("role") != "admin":
        conn.close()
        flash("Bạn không có quyền xóa bài này.", "danger")
        return redirect(url_for("my_posts"))
    conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    flash("Đã xóa bài đăng.", "success")
    return redirect(url_for("my_posts"))


# =========================
# ADMIN
# =========================
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    conn = connect_db()
    total_users   = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
    total_posts   = conn.execute("SELECT COUNT(*) AS total FROM posts").fetchone()["total"]
    active_posts  = conn.execute("SELECT COUNT(*) AS total FROM posts WHERE status='active'").fetchone()["total"]
    resolved_posts = conn.execute("SELECT COUNT(*) AS total FROM posts WHERE status='resolved'").fetchone()["total"]
    pending_posts = conn.execute("SELECT COUNT(*) AS total FROM posts WHERE status='pending_review'").fetchone()["total"]

    # Claim statistics
    total_claims   = conn.execute("SELECT COUNT(*) as c FROM claims").fetchone()["c"]
    pending_claims = conn.execute("SELECT COUNT(*) as c FROM claims WHERE status='pending'").fetchone()["c"]
    matched_claims = conn.execute("SELECT COUNT(*) as c FROM claims WHERE status IN ('matched','owner_confirmed')").fetchone()["c"]
    rejected_claims = conn.execute("SELECT COUNT(*) as c FROM claims WHERE status='rejected'").fetchone()["c"]
    match_rate = round(matched_claims / total_claims * 100) if total_claims else 0

    # Category breakdown (top 5)
    cat_stats = conn.execute("""
        SELECT category, COUNT(*) as cnt FROM posts
        WHERE status='active' GROUP BY category ORDER BY cnt DESC LIMIT 5
    """).fetchall()

    pending_review = conn.execute("""
        SELECT p.*, u.full_name,
               py.id as pay_id, py.payment_proof, py.amount as pay_amount,
               py.transfer_content, py.status as pay_status, py.package_name as pay_package_name
        FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        LEFT JOIN (
            SELECT * FROM payments WHERE id IN (
                SELECT MAX(id) FROM payments GROUP BY post_id
            )
        ) py ON py.post_id = p.id
        WHERE p.status='pending_review' ORDER BY p.id DESC
    """).fetchall()

    active_list = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.status='active' ORDER BY p.priority DESC, p.id DESC
    """).fetchall()

    other_posts = conn.execute("""
        SELECT p.*, u.full_name FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.status NOT IN ('pending_review', 'active') ORDER BY p.id DESC
    """).fetchall()

    vip_posts      = conn.execute("SELECT COUNT(*) as c FROM posts WHERE priority > 0 AND status='active'").fetchone()["c"]
    locked_users   = conn.execute("SELECT COUNT(*) as c FROM users WHERE is_locked=1").fetchone()["c"]
    pending_payments = conn.execute("SELECT COUNT(*) as c FROM payments WHERE status='pending'").fetchone()["c"]

    conn.close()
    return render_template(
        "admin.html",
        total_users=total_users, total_posts=total_posts,
        active_posts=active_posts, resolved_posts=resolved_posts,
        pending_posts=pending_posts,
        pending_review=pending_review, active_list=active_list, other_posts=other_posts,
        total_claims=total_claims, pending_claims=pending_claims,
        matched_claims=matched_claims, rejected_claims=rejected_claims,
        match_rate=match_rate, cat_stats=cat_stats,
        vip_posts=vip_posts, locked_users=locked_users, pending_payments=pending_payments,
    )


@app.route("/admin/payments")
@login_required
@admin_required
def admin_payments():
    status_filter = request.args.get("status", "")
    conn = connect_db()

    base_sql = """
        SELECT py.*, p.title, u.full_name, u.username
        FROM payments py
        LEFT JOIN posts p ON py.post_id = p.id
        LEFT JOIN users u ON py.user_id = u.id
    """
    params = []
    if status_filter in ("pending", "paid", "rejected"):
        base_sql += " WHERE py.status=?"
        params.append(status_filter)
    base_sql += " ORDER BY py.id DESC"

    payments = conn.execute(base_sql, params).fetchall()
    counts = {
        "all":      conn.execute("SELECT COUNT(*) as c FROM payments").fetchone()["c"],
        "pending":  conn.execute("SELECT COUNT(*) as c FROM payments WHERE status='pending'").fetchone()["c"],
        "paid":     conn.execute("SELECT COUNT(*) as c FROM payments WHERE status='paid'").fetchone()["c"],
        "rejected": conn.execute("SELECT COUNT(*) as c FROM payments WHERE status='rejected'").fetchone()["c"],
    }
    conn.close()
    return render_template("admin_payments.html", payments=payments,
                           status_filter=status_filter, counts=counts)


@app.route("/admin/payments/confirm/<int:payment_id>", methods=["POST"])
@login_required
@admin_required
def confirm_payment(payment_id):
    conn = connect_db()
    payment = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    if not payment:
        conn.close()
        flash("Không tìm thấy giao dịch.", "danger")
        return redirect(url_for("admin_payments"))

    package = VIP_PACKAGES.get(payment["package_key"])
    if not package:
        conn.close()
        flash("Gói thanh toán không hợp lệ.", "danger")
        return redirect(url_for("admin_payments"))

    now = datetime.now()
    conn.execute("UPDATE payments SET status='paid', confirmed_at=? WHERE id=?",
                 (str(now), payment_id))

    # Nếu bài đã active → bắt đầu VIP ngay
    post = conn.execute("SELECT * FROM posts WHERE id=?", (payment["post_id"],)).fetchone()
    if post and post["status"] == "active":
        days = package["days"]
        vip_start = str(now)
        vip_end = str(now + timedelta(days=days))
        conn.execute("""
            UPDATE posts SET priority=?, package_key=?, vip_started_at=?, vip_expires_at=? WHERE id=?
        """, (package["priority"], payment["package_key"], vip_start, vip_end, payment["post_id"]))
    else:
        conn.execute("UPDATE posts SET priority=?, package_key=? WHERE id=?",
                     (package["priority"], payment["package_key"], payment["post_id"]))

    log_admin_action(conn, f"Xác nhận thanh toán #{payment_id} → gói {package['name']}",
                     "payment", payment_id, f"Post #{payment['post_id']}")
    conn.commit()
    conn.close()
    flash("Đã xác nhận thanh toán và nâng cấp bài đăng.", "success")
    return redirect(url_for("admin_payments"))


@app.route("/admin/payments/reject/<int:payment_id>", methods=["POST"])
@login_required
@admin_required
def reject_payment(payment_id):
    conn = connect_db()
    payment = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    if not payment:
        conn.close()
        flash("Không tìm thấy giao dịch.", "danger")
        return redirect(url_for("admin_payments"))
    conn.execute("UPDATE payments SET status='rejected', confirmed_at=? WHERE id=?",
                 (str(datetime.now()), payment_id))
    log_admin_action(conn, f"Từ chối thanh toán #{payment_id}", "payment", payment_id)
    conn.commit()
    conn.close()
    flash("Đã từ chối giao dịch.", "warning")
    return redirect(url_for("admin_payments"))


@app.route("/admin/claims")
@login_required
@admin_required
def admin_claims():
    status_filter = request.args.get("status", "")
    conn = connect_db()

    base_sql = """
        SELECT c.*, p_lost.title as lost_title, p_found.title as found_title,
               u.full_name as claimer_name, u.username as claimer_username,
               p_found.contact as found_contact
        FROM claims c
        LEFT JOIN posts p_lost ON c.lost_post_id = p_lost.id
        LEFT JOIN posts p_found ON c.found_post_id = p_found.id
        LEFT JOIN users u ON c.claimer_user_id = u.id
    """
    params = []
    if status_filter in ("pending", "matched", "low_match", "rejected", "owner_confirmed"):
        base_sql += " WHERE c.status=?"
        params.append(status_filter)
    base_sql += " ORDER BY c.id DESC"

    claims = conn.execute(base_sql, params).fetchall()
    claim_counts = {
        "all":       conn.execute("SELECT COUNT(*) as c FROM claims").fetchone()["c"],
        "pending":   conn.execute("SELECT COUNT(*) as c FROM claims WHERE status='pending'").fetchone()["c"],
        "matched":   conn.execute("SELECT COUNT(*) as c FROM claims WHERE status IN ('matched','owner_confirmed')").fetchone()["c"],
        "low_match": conn.execute("SELECT COUNT(*) as c FROM claims WHERE status='low_match'").fetchone()["c"],
        "rejected":  conn.execute("SELECT COUNT(*) as c FROM claims WHERE status='rejected'").fetchone()["c"],
    }
    conn.close()
    return render_template("admin_claims.html", claims=claims,
                           status_filter=status_filter, claim_counts=claim_counts)


@app.route("/admin/claims/update/<int:claim_id>", methods=["POST"])
@login_required
@admin_required
def update_claim_status(claim_id):
    status = request.form.get("status")
    override_score = request.form.get("override_score", "").strip()

    if status not in ["pending", "matched", "low_match", "rejected"]:
        flash("Trạng thái không hợp lệ.", "danger")
        return redirect(url_for("admin_claims"))

    conn = connect_db()
    # Khi admin duyệt "matched" → tự động unlock contact
    contact_unlocked_val = 1 if status == "matched" else 0

    update_fields = "status=?, contact_unlocked=?"
    params = [status, contact_unlocked_val]

    # Admin có thể override điểm AI
    if override_score and override_score.isdigit():
        score = min(100, max(0, int(override_score)))
        update_fields += ", ai_score=?"
        params.append(score)

    params.append(claim_id)
    conn.execute(f"UPDATE claims SET {update_fields} WHERE id=?", params)
    log_admin_action(conn, f"Cập nhật claim #{claim_id} → {status}", "claim", claim_id)
    conn.commit()
    conn.close()

    label = {"matched": "Duyệt khớp", "rejected": "Từ chối", "low_match": "Khớp thấp", "pending": "Chờ xử lý"}
    flash(f"Đã cập nhật claim → {label.get(status, status)}.", "success")
    return redirect(url_for("admin_claims"))


@app.route("/admin/priority/<int:post_id>", methods=["POST"])
@login_required
@admin_required
def update_priority(post_id):
    priority = int(request.form.get("priority", 0))
    if priority < 0 or priority > 3:
        priority = 0
    conn = connect_db()
    conn.execute("UPDATE posts SET priority=? WHERE id=?", (priority, post_id))
    conn.commit()
    conn.close()
    flash("Cập nhật độ ưu tiên thành công.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/post/approve/<int:post_id>", methods=["POST"])
@login_required
@admin_required
def admin_approve_post(post_id):
    conn = connect_db()
    post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        conn.close()
        flash("Không tìm thấy bài đăng.", "danger")
        return redirect(url_for("admin_dashboard"))

    now = datetime.now()
    vip_started_at = vip_expires_at = None
    pkg_key = post["package_key"] if post["package_key"] else None

    # Chỉ bắt đầu VIP khi có payment đã được xác nhận
    if pkg_key and pkg_key in VIP_PACKAGES:
        paid = conn.execute(
            "SELECT id FROM payments WHERE post_id=? AND status='paid' LIMIT 1",
            (post_id,)
        ).fetchone()
        if paid:
            days = VIP_PACKAGES[pkg_key]["days"]
            vip_started_at = str(now)
            vip_expires_at = str(now + timedelta(days=days))

    conn.execute("""
        UPDATE posts SET status='active', vip_started_at=?, vip_expires_at=? WHERE id=?
    """, (vip_started_at, vip_expires_at, post_id))
    log_admin_action(conn, f"Duyệt bài #{post_id}", "post", post_id,
                     f"VIP: {pkg_key or 'không'}, expires: {vip_expires_at or 'N/A'}")
    owner = conn.execute("SELECT email, full_name FROM users WHERE id=?", (post["user_id"],)).fetchone()
    conn.commit()
    conn.close()
    if owner and owner["email"]:
        send_email(owner["email"], f"Bài đăng #{post_id} đã được duyệt",
            f"<p>Xin chào <strong>{owner['full_name']}</strong>,</p>"
            f"<p>Bài đăng <strong>#{post_id}: {post['title']}</strong> đã được admin duyệt và đang hiển thị trên PTIT Lost &amp; Found.</p>"
            f"<p><a href='{request.host_url}post/{post_id}'>Xem bài đăng →</a></p>")
    flash(f"Đã duyệt bài đăng #{post_id} thành công.", "success")
    return redirect(url_for("admin_posts"))


@app.route("/admin/post/reject/<int:post_id>", methods=["POST"])
@login_required
@admin_required
def admin_reject_post(post_id):
    conn = connect_db()
    post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    conn.execute("UPDATE posts SET status='rejected' WHERE id=?", (post_id,))
    log_admin_action(conn, f"Từ chối bài #{post_id}", "post", post_id)
    owner = conn.execute("SELECT email, full_name FROM users WHERE id=?", (post["user_id"],)).fetchone() if post else None
    conn.commit()
    conn.close()
    if owner and owner["email"]:
        send_email(owner["email"], f"Bài đăng #{post_id} bị từ chối",
            f"<p>Xin chào <strong>{owner['full_name']}</strong>,</p>"
            f"<p>Bài đăng <strong>#{post_id}: {post['title']}</strong> đã bị admin từ chối.</p>"
            f"<p>Vui lòng kiểm tra lại nội dung và đăng lại nếu cần.</p>")
    flash(f"Đã từ chối bài đăng #{post_id}.", "warning")
    return redirect(url_for("admin_posts"))


# =========================
# ADMIN: QUẢN LÝ NGƯỜI DÙNG
# =========================
@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    conn = connect_db()
    users = conn.execute("""
        SELECT u.*,
               COUNT(DISTINCT p.id)  as post_count,
               COUNT(DISTINCT c.id)  as claim_count
        FROM users u
        LEFT JOIN posts  p ON p.user_id          = u.id
        LEFT JOIN claims c ON c.claimer_user_id  = u.id
        GROUP BY u.id ORDER BY u.id DESC
    """).fetchall()
    conn.close()
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/<int:user_id>/toggle-admin", methods=["POST"])
@login_required
@admin_required
def toggle_admin(user_id):
    if user_id == session["user_id"]:
        flash("Bạn không thể thay đổi quyền của chính mình.", "warning")
        return redirect(url_for("admin_users"))
    conn = connect_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        flash("Không tìm thấy người dùng.", "danger")
        return redirect(url_for("admin_users"))
    # Không cho gỡ admin cuối cùng
    if user["role"] == "admin":
        admin_count = conn.execute("SELECT COUNT(*) as c FROM users WHERE role='admin'").fetchone()["c"]
        if admin_count <= 1:
            conn.close()
            flash("Không thể gỡ quyền admin cuối cùng trong hệ thống.", "danger")
            return redirect(url_for("admin_users"))
    new_role = "user" if user["role"] == "admin" else "admin"
    conn.execute("UPDATE users SET role=? WHERE id=?", (new_role, user_id))
    log_admin_action(conn, f"Đổi role @{user['username']} → {new_role}", "user", user_id)
    conn.commit()
    conn.close()
    label = "Quản trị viên" if new_role == "admin" else "người dùng thường"
    flash(f"Đã chuyển @{user['username']} thành {label}.", "success")
    return redirect(url_for("admin_users"))


# =========================
# ADMIN: ẨN / KHÔI PHỤC / XÓA BÀI
# =========================
@app.route("/admin/post/hide/<int:post_id>", methods=["POST"])
@login_required
@admin_required
def admin_hide_post(post_id):
    conn = connect_db()
    conn.execute("UPDATE posts SET status='hidden' WHERE id=?", (post_id,))
    log_admin_action(conn, f"Ẩn bài #{post_id}", "post", post_id)
    conn.commit()
    conn.close()
    flash(f"Đã ẩn bài đăng #{post_id}.", "warning")
    return redirect(url_for("admin_posts"))


@app.route("/admin/post/reactivate/<int:post_id>", methods=["POST"])
@login_required
@admin_required
def admin_reactivate_post(post_id):
    conn = connect_db()
    conn.execute("UPDATE posts SET status='active' WHERE id=?", (post_id,))
    log_admin_action(conn, f"Khôi phục bài #{post_id}", "post", post_id)
    conn.commit()
    conn.close()
    flash(f"Đã khôi phục bài đăng #{post_id} thành active.", "success")
    return redirect(url_for("admin_posts"))


@app.route("/admin/post/delete/<int:post_id>", methods=["POST"])
@login_required
@admin_required
def admin_delete_post(post_id):
    conn = connect_db()
    conn.execute("DELETE FROM claims WHERE found_post_id=? OR lost_post_id=?", (post_id, post_id))
    conn.execute("DELETE FROM payments WHERE post_id=?", (post_id,))
    log_admin_action(conn, f"Xóa bài #{post_id}", "post", post_id)
    conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    flash(f"Đã xóa bài đăng #{post_id} và toàn bộ dữ liệu liên quan.", "info")
    return redirect(url_for("admin_posts"))


# =========================
# ADMIN: QUẢN LÝ BÀI ĐĂNG (trang riêng)
# =========================
@app.route("/admin/posts")
@login_required
@admin_required
def admin_posts():
    status_filter = request.args.get("status", "")
    type_filter   = request.args.get("post_type", "")
    pkg_filter    = request.args.get("package", "")
    search_q      = request.args.get("q", "").strip()
    conn = connect_db()

    sql = """
        SELECT p.*, u.full_name, u.username,
               py.id as pay_id, py.payment_proof, py.amount as pay_amount,
               py.transfer_content, py.status as pay_status, py.package_name
        FROM posts p
        LEFT JOIN users u ON p.user_id = u.id
        LEFT JOIN (
            SELECT * FROM payments WHERE id IN (
                SELECT MAX(id) FROM payments GROUP BY post_id
            )
        ) py ON py.post_id = p.id
        WHERE 1=1
    """
    params = []
    if status_filter:
        sql += " AND p.status=?"
        params.append(status_filter)
    if type_filter in ("lost", "found"):
        sql += " AND p.post_type=?"
        params.append(type_filter)
    if pkg_filter:
        sql += " AND p.package_key=?"
        params.append(pkg_filter)
    if search_q:
        sql += " AND (p.title LIKE ? OR CAST(p.id AS TEXT)=?)"
        params += [f"%{search_q}%", search_q]
    sql += " ORDER BY p.priority DESC, p.id DESC"

    posts = conn.execute(sql, params).fetchall()
    counts = {
        s: conn.execute("SELECT COUNT(*) as c FROM posts WHERE status=?", (s,)).fetchone()["c"]
        for s in ("pending_review", "active", "rejected", "hidden", "resolved")
    }
    counts["vip"] = conn.execute(
        "SELECT COUNT(*) as c FROM posts WHERE priority > 0 AND status='active'"
    ).fetchone()["c"]
    counts["all"] = conn.execute("SELECT COUNT(*) as c FROM posts").fetchone()["c"]
    conn.close()
    return render_template("admin_posts.html", posts=posts, counts=counts,
                           status_filter=status_filter, type_filter=type_filter,
                           pkg_filter=pkg_filter, search_q=search_q,
                           vip_packages=VIP_PACKAGES,
                           now_str=str(datetime.now())[:10])


@app.route("/admin/post/mark-resolved/<int:post_id>", methods=["POST"])
@login_required
@admin_required
def admin_mark_resolved(post_id):
    conn = connect_db()
    conn.execute("UPDATE posts SET status='resolved' WHERE id=?", (post_id,))
    log_admin_action(conn, f"Đánh dấu đã xử lý bài #{post_id}", "post", post_id)
    conn.commit()
    conn.close()
    flash(f"Đã đánh dấu bài #{post_id} là đã xử lý.", "success")
    return redirect(url_for("admin_posts"))


# =========================
# ADMIN: QUẢN LÝ VIP
# =========================
@app.route("/admin/vip/extend/<int:post_id>", methods=["POST"])
@login_required
@admin_required
def admin_vip_extend(post_id):
    try:
        days = int(request.form.get("days", 0))
    except (ValueError, TypeError):
        days = 0
    if days <= 0:
        flash("Số ngày gia hạn không hợp lệ.", "danger")
        return redirect(url_for("admin_posts"))
    conn = connect_db()
    post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        conn.close()
        flash("Không tìm thấy bài đăng.", "danger")
        return redirect(url_for("admin_posts"))

    now = datetime.now()
    if post["vip_expires_at"]:
        try:
            current_exp = datetime.fromisoformat(post["vip_expires_at"][:19])
            base = current_exp if current_exp > now else now
        except Exception:
            base = now
    else:
        base = now

    new_exp = str(base + timedelta(days=days))
    vip_start = post["vip_started_at"] or str(now)
    pkg_key = post["package_key"] or "goi_1"
    priority = post["priority"] if post["priority"] > 0 else VIP_PACKAGES.get(pkg_key, {}).get("priority", 1)

    conn.execute("""
        UPDATE posts SET vip_started_at=?, vip_expires_at=?, priority=?, package_key=? WHERE id=?
    """, (vip_start, new_exp, priority, pkg_key, post_id))
    log_admin_action(conn, f"Gia hạn VIP +{days} ngày bài #{post_id}", "post", post_id,
                     f"Hết hạn mới: {new_exp}")
    conn.commit()
    conn.close()
    flash(f"Đã gia hạn VIP +{days} ngày cho bài #{post_id}. Hết hạn: {new_exp[:10]}.", "success")
    return redirect(url_for("admin_posts"))


@app.route("/admin/vip/change-package/<int:post_id>", methods=["POST"])
@login_required
@admin_required
def admin_vip_change_package(post_id):
    new_pkg = request.form.get("package_key", "")
    conn = connect_db()
    post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        conn.close()
        flash("Không tìm thấy bài đăng.", "danger")
        return redirect(url_for("admin_posts"))

    if new_pkg == "free":
        # Hạ về tin thường
        conn.execute("""
            UPDATE posts SET package_key=NULL, priority=0,
                vip_started_at=NULL, vip_expires_at=NULL WHERE id=?
        """, (post_id,))
        log_admin_action(conn, f"Gỡ VIP bài #{post_id}", "post", post_id)
        flash(f"Đã gỡ VIP bài #{post_id} → Tin thường.", "success")
    elif new_pkg in VIP_PACKAGES:
        pkg = VIP_PACKAGES[new_pkg]
        now = datetime.now()
        vip_start = str(now)
        vip_end = str(now + timedelta(days=pkg["days"]))
        conn.execute("""
            UPDATE posts SET package_key=?, priority=?, vip_started_at=?, vip_expires_at=? WHERE id=?
        """, (new_pkg, pkg["priority"], vip_start, vip_end, post_id))
        log_admin_action(conn, f"Đổi gói VIP bài #{post_id} → {pkg['name']}", "post", post_id)
        flash(f"Đã nâng/hạ bài #{post_id} lên gói {pkg['name']}.", "success")
    else:
        conn.close()
        flash("Gói không hợp lệ.", "danger")
        return redirect(url_for("admin_posts"))

    conn.commit()
    conn.close()
    return redirect(url_for("admin_posts"))


@app.route("/admin/vip/set-expiry/<int:post_id>", methods=["POST"])
@login_required
@admin_required
def admin_vip_set_expiry(post_id):
    new_date = request.form.get("expiry_date", "").strip()
    if not new_date:
        flash("Vui lòng nhập ngày hết hạn.", "danger")
        return redirect(url_for("admin_posts"))
    try:
        exp_dt = datetime.fromisoformat(new_date)
    except ValueError:
        flash("Định dạng ngày không hợp lệ (YYYY-MM-DD hoặc YYYY-MM-DDTHH:MM).", "danger")
        return redirect(url_for("admin_posts"))
    conn = connect_db()
    conn.execute("UPDATE posts SET vip_expires_at=? WHERE id=?", (str(exp_dt), post_id))
    log_admin_action(conn, f"Sửa ngày hết hạn VIP bài #{post_id}", "post", post_id,
                     f"→ {exp_dt.strftime('%Y-%m-%d %H:%M')}")
    conn.commit()
    conn.close()
    flash(f"Đã cập nhật ngày hết hạn VIP bài #{post_id} → {exp_dt.strftime('%Y-%m-%d')}.", "success")
    return redirect(url_for("admin_posts"))


@app.route("/admin/vip/set-priority/<int:post_id>", methods=["POST"])
@login_required
@admin_required
def admin_vip_set_priority(post_id):
    priority = request.form.get("priority", "0")
    try:
        priority = max(0, min(10, int(priority)))
    except ValueError:
        priority = 0
    conn = connect_db()
    conn.execute("UPDATE posts SET priority=? WHERE id=?", (priority, post_id))
    log_admin_action(conn, f"Chỉnh ưu tiên thủ công bài #{post_id} → {priority}", "post", post_id)
    conn.commit()
    conn.close()
    flash(f"Đã cập nhật độ ưu tiên bài #{post_id} → {priority}.", "success")
    return redirect(url_for("admin_posts"))


# =========================
# ADMIN: KHÓA / MỞ KHÓA USER
# =========================
@app.route("/admin/users/<int:user_id>/lock", methods=["POST"])
@login_required
@admin_required
def admin_lock_user(user_id):
    if user_id == session["user_id"]:
        flash("Bạn không thể tự khóa tài khoản của mình.", "warning")
        return redirect(url_for("admin_users"))
    conn = connect_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        flash("Không tìm thấy người dùng.", "danger")
        return redirect(url_for("admin_users"))
    new_locked = 0 if user["is_locked"] else 1
    conn.execute("UPDATE users SET is_locked=? WHERE id=?", (new_locked, user_id))
    action = "Khóa" if new_locked else "Mở khóa"
    log_admin_action(conn, f"{action} tài khoản @{user['username']}", "user", user_id)
    conn.commit()
    conn.close()
    flash(f"Đã {action.lower()} tài khoản @{user['username']}.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/claims/<int:claim_id>/toggle-contact", methods=["POST"])
@login_required
@admin_required
def admin_toggle_contact(claim_id):
    conn = connect_db()
    claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    if not claim:
        conn.close()
        flash("Không tìm thấy claim.", "danger")
        return redirect(url_for("admin_claims"))
    new_val = 0 if claim["contact_unlocked"] else 1
    conn.execute("UPDATE claims SET contact_unlocked=? WHERE id=?", (new_val, claim_id))
    action = "Mở khóa contact" if new_val else "Khóa contact"
    log_admin_action(conn, f"{action} claim #{claim_id}", "claim", claim_id)
    conn.commit()
    conn.close()
    flash(f"Đã {action.lower()} cho claim #{claim_id}.", "success")
    return redirect(url_for("admin_claims"))


# =========================
# AI: PHÂN TÍCH ẢNH
# =========================
@app.route("/api/analyze-image", methods=["POST"])
@login_required
def analyze_image_api():
    from flask import jsonify
    if "image" not in request.files:
        return jsonify({"error": "no_file"}), 400
    file = request.files["image"]
    if not file or not allowed_file(file.filename):
        return jsonify({"error": "invalid_file"}), 400
    filename = save_uploaded_file(file)
    if not filename:
        return jsonify({"error": "save_failed"}), 500
    image_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    result = claude_analyze_image(image_path)
    try:
        os.remove(image_path)
    except Exception:
        pass
    if result:
        return jsonify(result)
    return jsonify({"error": "ai_unavailable"}), 503


# =========================
# CHAT NỘI BỘ
# =========================
@app.route("/my-chats")
@login_required
def my_chats():
    user_id = session["user_id"]
    conn = connect_db()
    chats = conn.execute("""
        SELECT c.id as claim_id, c.status,
               fp.title as found_title, fp.id as found_post_id,
               cu.full_name as claimer_name, cu.id as claimer_id,
               ou.full_name as owner_name, ou.id as owner_id,
               (SELECT COUNT(*) FROM chat_messages m
                WHERE m.claim_id = c.id AND m.is_read = 0 AND m.sender_id != ?) as unread,
               (SELECT m2.message FROM chat_messages m2
                WHERE m2.claim_id = c.id ORDER BY m2.id DESC LIMIT 1) as last_message,
               (SELECT m3.created_at FROM chat_messages m3
                WHERE m3.claim_id = c.id ORDER BY m3.id DESC LIMIT 1) as last_at
        FROM claims c
        JOIN posts fp ON c.found_post_id = fp.id
        JOIN users cu ON c.claimer_user_id = cu.id
        JOIN users ou ON fp.user_id = ou.id
        WHERE c.status = 'owner_confirmed'
          AND (c.claimer_user_id = ? OR fp.user_id = ?)
        ORDER BY c.id DESC
    """, (user_id, user_id, user_id)).fetchall()
    conn.close()
    return render_template("my_chats.html", chats=chats)


@app.route("/chat/<int:claim_id>")
@login_required
def chat_view(claim_id):
    conn = connect_db()
    claim = conn.execute("""
        SELECT c.*, fp.title as found_title, fp.user_id as found_owner_id,
               fp.id as found_post_id_val,
               cu.full_name as claimer_name, cu.id as claimer_id,
               ou.full_name as owner_name
        FROM claims c
        LEFT JOIN posts fp ON c.found_post_id = fp.id
        LEFT JOIN users cu ON c.claimer_user_id = cu.id
        LEFT JOIN users ou ON fp.user_id = ou.id
        WHERE c.id=?
    """, (claim_id,)).fetchone()
    if not claim:
        conn.close()
        flash("Không tìm thấy cuộc trò chuyện.", "danger")
        return redirect(url_for("home"))
    user_id = session["user_id"]
    if user_id not in (claim["claimer_id"], claim["found_owner_id"]) and session.get("role") != "admin":
        conn.close()
        flash("Bạn không có quyền truy cập.", "danger")
        return redirect(url_for("home"))
    if claim["status"] != "owner_confirmed":
        conn.close()
        flash("Chat chỉ khả dụng sau khi chủ đã xác nhận.", "warning")
        return redirect(url_for("post_detail", post_id=claim["found_post_id"]))
    conn.execute("UPDATE chat_messages SET is_read=1 WHERE claim_id=? AND sender_id!=?", (claim_id, user_id))
    messages = conn.execute("""
        SELECT m.*, u.full_name, u.username
        FROM chat_messages m JOIN users u ON m.sender_id = u.id
        WHERE m.claim_id=? ORDER BY m.id ASC
    """, (claim_id,)).fetchall()
    conn.commit()
    conn.close()
    other_name = claim["claimer_name"] if user_id == claim["found_owner_id"] else claim["owner_name"]
    return render_template("chat.html", claim=claim, messages=messages, other_name=other_name)


@app.route("/chat/<int:claim_id>/send", methods=["POST"])
@login_required
def chat_send(claim_id):
    message = request.form.get("message", "").strip()
    if not message or len(message) > 1000:
        return redirect(url_for("chat_view", claim_id=claim_id))
    conn = connect_db()
    claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    if not claim:
        conn.close()
        return redirect(url_for("home"))
    found_owner_id = conn.execute("SELECT user_id FROM posts WHERE id=?", (claim["found_post_id"],)).fetchone()["user_id"]
    user_id = session["user_id"]
    if user_id not in (claim["claimer_user_id"], found_owner_id) and session.get("role") != "admin":
        conn.close()
        return redirect(url_for("home"))
    if claim["status"] != "owner_confirmed":
        conn.close()
        return redirect(url_for("post_detail", post_id=claim["found_post_id"]))
    conn.execute(
        "INSERT INTO chat_messages (claim_id, sender_id, message, created_at) VALUES (?,?,?,?)",
        (claim_id, user_id, message, str(datetime.now()))
    )
    conn.commit()
    conn.close()
    return redirect(url_for("chat_view", claim_id=claim_id))


@app.route("/chat/<int:claim_id>/stream")
@login_required
def chat_stream(claim_id):
    """SSE endpoint — đẩy tin nhắn mới về client không cần polling."""
    from flask import Response, stream_with_context
    import time as _time

    user_id = session["user_id"]

    def _check_access():
        conn = connect_db()
        claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not claim:
            conn.close()
            return False, None
        owner_id = conn.execute(
            "SELECT user_id FROM posts WHERE id=?", (claim["found_post_id"],)
        ).fetchone()["user_id"]
        conn.close()
        return user_id in (claim["claimer_user_id"], owner_id), claim

    ok, _ = _check_access()
    if not ok:
        return Response("data: {}\n\n", status=403, mimetype="text/event-stream")

    def _generate():
        last_id = 0
        # Gửi tất cả tin cũ lần đầu
        conn = connect_db()
        rows = conn.execute(
            "SELECT m.id, m.sender_id, m.message, m.created_at, u.full_name "
            "FROM chat_messages m JOIN users u ON m.sender_id=u.id "
            "WHERE m.claim_id=? ORDER BY m.id ASC", (claim_id,)
        ).fetchall()
        conn.execute(
            "UPDATE chat_messages SET is_read=1 WHERE claim_id=? AND sender_id!=?",
            (claim_id, user_id)
        )
        conn.commit()
        conn.close()
        if rows:
            last_id = rows[-1]["id"]
            for r in rows:
                yield f"data: {json.dumps(dict(r))}\n\n"
        # Polling loop — gửi khi có tin mới
        while True:
            _time.sleep(2)
            conn = connect_db()
            new_rows = conn.execute(
                "SELECT m.id, m.sender_id, m.message, m.created_at, u.full_name "
                "FROM chat_messages m JOIN users u ON m.sender_id=u.id "
                "WHERE m.claim_id=? AND m.id>? ORDER BY m.id ASC",
                (claim_id, last_id)
            ).fetchall()
            if new_rows:
                conn.execute(
                    "UPDATE chat_messages SET is_read=1 WHERE claim_id=? AND sender_id!=? AND id>?",
                    (claim_id, user_id, last_id)
                )
                conn.commit()
                last_id = new_rows[-1]["id"]
            conn.close()
            for r in new_rows:
                yield f"data: {json.dumps(dict(r))}\n\n"
            yield ": keepalive\n\n"

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.route("/chat/<int:claim_id>/messages")
@login_required
def chat_poll(claim_id):
    from flask import jsonify
    after_id = int(request.args.get("after", 0))
    conn = connect_db()
    claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    if not claim:
        conn.close()
        return jsonify({"messages": []}), 404
    found_owner_id = conn.execute("SELECT user_id FROM posts WHERE id=?", (claim["found_post_id"],)).fetchone()["user_id"]
    user_id = session["user_id"]
    if user_id not in (claim["claimer_user_id"], found_owner_id):
        conn.close()
        return jsonify({"messages": []}), 403
    rows = conn.execute("""
        SELECT m.id, m.sender_id, m.message, m.created_at, u.full_name
        FROM chat_messages m JOIN users u ON m.sender_id = u.id
        WHERE m.claim_id=? AND m.id > ? ORDER BY m.id ASC
    """, (claim_id, after_id)).fetchall()
    conn.execute("UPDATE chat_messages SET is_read=1 WHERE claim_id=? AND sender_id!=? AND id>?",
                 (claim_id, user_id, after_id))
    conn.commit()
    conn.close()
    return jsonify({"messages": [dict(r) for r in rows]})


# =========================
# ADMIN: THỐNG KÊ DOANH THU
# =========================
@app.route("/admin/revenue")
@login_required
@admin_required
def admin_revenue():
    period   = request.args.get("period", "month")   # day | week | month
    from_dt  = request.args.get("from", "")
    to_dt    = request.args.get("to", "")
    conn = connect_db()

    # Điều kiện lọc ngày
    date_cond, date_params = "", []
    if from_dt:
        date_cond += " AND date(created_at) >= ?"
        date_params.append(from_dt)
    if to_dt:
        date_cond += " AND date(created_at) <= ?"
        date_params.append(to_dt)

    # Tổng doanh thu
    total_revenue = conn.execute(
        f"SELECT COALESCE(SUM(amount),0) as t FROM payments WHERE status='paid'{date_cond}",
        date_params
    ).fetchone()["t"]
    total_count = conn.execute(
        f"SELECT COUNT(*) as c FROM payments WHERE status='paid'{date_cond}",
        date_params
    ).fetchone()["c"]
    pending_count = conn.execute(
        "SELECT COUNT(*) as c FROM payments WHERE status='pending'"
    ).fetchone()["c"]

    # Thống kê theo gói VIP
    by_package = conn.execute(f"""
        SELECT package_key, package_name,
               COUNT(*) as cnt,
               COALESCE(SUM(amount),0) as total
        FROM payments
        WHERE status='paid'{date_cond}
        GROUP BY package_key
        ORDER BY total DESC
    """, date_params).fetchall()

    # Group theo kỳ
    if period == "day":
        grp = "date(created_at)"
        lbl = "Ngày"
    elif period == "week":
        grp = "strftime('%Y-W%W', created_at)"
        lbl = "Tuần"
    else:
        grp = "strftime('%Y-%m', created_at)"
        lbl = "Tháng"

    by_period = conn.execute(f"""
        SELECT {grp} as period_key,
               COUNT(*) as cnt,
               COALESCE(SUM(amount),0) as total
        FROM payments
        WHERE status='paid'{date_cond}
        GROUP BY {grp}
        ORDER BY period_key DESC
        LIMIT 24
    """, date_params).fetchall()

    # Đảo chiều để chart hiển thị từ cũ→mới
    by_period_asc = list(reversed(list(by_period)))

    conn.close()
    return render_template("admin_revenue.html",
        total_revenue=total_revenue, total_count=total_count,
        pending_count=pending_count,
        by_package=by_package, by_period=by_period, by_period_asc=by_period_asc,
        period=period, period_lbl=lbl,
        from_dt=from_dt, to_dt=to_dt,
        vip_packages=VIP_PACKAGES)


# =========================
# ADMIN: NHẬT KÝ THAO TÁC
# =========================
@app.route("/admin/logs")
@login_required
@admin_required
def admin_logs():
    page = request.args.get("page", 1, type=int) or 1
    per_page = 50
    offset = (page - 1) * per_page
    conn = connect_db()
    total = conn.execute("SELECT COUNT(*) as c FROM admin_logs").fetchone()["c"]
    logs = conn.execute(
        "SELECT * FROM admin_logs ORDER BY id DESC LIMIT ? OFFSET ?",
        (per_page, offset)
    ).fetchall()
    conn.close()
    total_pages = (total + per_page - 1) // per_page
    return render_template("admin_logs.html", logs=logs, page=page,
                           total_pages=total_pages, total=total)


# =========================
# NGƯỜI NHẶT XEM CLAIM
# =========================
@app.route("/my-received-claims")
@login_required
def my_received_claims():
    conn = connect_db()
    claims = conn.execute("""
        SELECT c.*, p_found.title as found_title, p_found.id as found_id,
               p_lost.title as lost_title,
               u.full_name as claimer_name, u.username as claimer_username
        FROM claims c
        LEFT JOIN posts p_found ON c.found_post_id = p_found.id
        LEFT JOIN posts p_lost  ON c.lost_post_id  = p_lost.id
        LEFT JOIN users u       ON c.claimer_user_id = u.id
        WHERE p_found.user_id=? ORDER BY c.id DESC
    """, (session["user_id"],)).fetchall()
    conn.close()
    return render_template("my_received_claims.html", claims=claims)


@app.route("/claim/confirm/<int:claim_id>", methods=["POST"])
@login_required
def confirm_claim_owner(claim_id):
    conn = connect_db()
    claim = conn.execute("""
        SELECT c.*, p.user_id as owner_id FROM claims c
        LEFT JOIN posts p ON c.found_post_id = p.id WHERE c.id=?
    """, (claim_id,)).fetchone()

    if not claim or claim["owner_id"] != session["user_id"]:
        conn.close()
        flash("Bạn không có quyền thực hiện thao tác này.", "danger")
        return redirect(url_for("my_received_claims"))

    conn.execute("""
        UPDATE claims SET status='owner_confirmed', owner_confirmed=1,
            contact_unlocked=1, owner_reviewed_at=? WHERE id=?
    """, (str(datetime.now()), claim_id))
    conn.commit()
    conn.close()
    flash("Đã xác nhận đúng chủ. Người mất đồ có thể xem thông tin liên hệ.", "success")
    return redirect(url_for("my_received_claims"))


@app.route("/claim/reject-owner/<int:claim_id>", methods=["POST"])
@login_required
def reject_claim_owner(claim_id):
    conn = connect_db()
    claim = conn.execute("""
        SELECT c.*, p.user_id as owner_id FROM claims c
        LEFT JOIN posts p ON c.found_post_id = p.id WHERE c.id=?
    """, (claim_id,)).fetchone()

    if not claim or claim["owner_id"] != session["user_id"]:
        conn.close()
        flash("Bạn không có quyền thực hiện thao tác này.", "danger")
        return redirect(url_for("my_received_claims"))

    conn.execute("UPDATE claims SET status='rejected', owner_reviewed_at=? WHERE id=?",
                 (str(datetime.now()), claim_id))
    conn.commit()
    conn.close()
    flash("Đã từ chối yêu cầu nhận đồ.", "info")
    return redirect(url_for("my_received_claims"))


# =========================
# FORCED PASSWORD CHANGE
# =========================
@app.route("/change-password-forced", methods=["GET", "POST"])
@login_required
def change_password_forced():
    if request.method == "POST":
        new_pass = request.form.get("new_password", "").strip()
        confirm  = request.form.get("confirm_password", "").strip()
        if len(new_pass) < 6:
            flash("Mật khẩu mới phải có ít nhất 6 ký tự.", "danger")
            return redirect(url_for("change_password_forced"))
        if new_pass != confirm:
            flash("Mật khẩu xác nhận không khớp.", "danger")
            return redirect(url_for("change_password_forced"))
        conn = connect_db()
        conn.execute("UPDATE users SET password=?, force_password_change=0 WHERE id=?",
                     (generate_password_hash(new_pass), session["user_id"]))
        conn.commit()
        conn.close()
        flash("Đã đổi mật khẩu thành công.", "success")
        return redirect(url_for("home"))
    return render_template("change_password_forced.html")


# =========================
# ADMIN: CÀI ĐẶT HỆ THỐNG
# =========================
@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
@admin_required
def admin_settings():
    if request.method == "POST":
        keys = [
            "site_name", "site_description", "contact_phone", "contact_email", "contact_address",
            "bank_name", "bank_account", "bank_owner",
            "feature_vip", "feature_ai", "feature_chat", "feature_comments",
            "max_posts_per_user", "max_image_size_mb", "auto_hide_resolved_days",
            "vip_goi_1_name", "vip_goi_1_price", "vip_goi_1_days", "vip_goi_1_priority", "vip_goi_1_label",
            "vip_goi_2_name", "vip_goi_2_price", "vip_goi_2_days", "vip_goi_2_priority", "vip_goi_2_label",
            "vip_goi_3_name", "vip_goi_3_price", "vip_goi_3_days", "vip_goi_3_priority", "vip_goi_3_label",
        ]
        conn = connect_db()
        for k in keys:
            val = request.form.get(k, "").strip()
            conn.execute("INSERT OR REPLACE INTO site_settings (key, value, updated_at) VALUES (?, ?, ?)",
                         (k, val, str(datetime.now())))
        log_admin_action(conn, "Cập nhật cài đặt hệ thống", "settings", None)
        conn.commit()
        conn.close()
        flash("Đã lưu cài đặt hệ thống.", "success")
        return redirect(url_for("admin_settings"))
    settings = get_all_settings()
    return render_template("admin_settings.html", s=settings)


# =========================
# ADMIN: DANH MỤC
# =========================
@app.route("/admin/categories")
@login_required
@admin_required
def admin_categories():
    conn = connect_db()
    cats = conn.execute("SELECT * FROM categories ORDER BY sort_order, id").fetchall()
    conn.close()
    return render_template("admin_categories.html", cats=cats)


@app.route("/admin/categories/add", methods=["POST"])
@login_required
@admin_required
def admin_category_add():
    name  = request.form.get("name", "").strip()
    icon  = request.form.get("icon", "📦").strip()
    order = request.form.get("sort_order", "99").strip()
    if not name:
        flash("Tên danh mục không được để trống.", "danger")
        return redirect(url_for("admin_categories"))
    conn = connect_db()
    try:
        conn.execute("INSERT INTO categories (name, icon, sort_order, created_at) VALUES (?,?,?,?)",
                     (name, icon, int(order) if order.isdigit() else 99, str(datetime.now())))
        log_admin_action(conn, f"Thêm danh mục: {name}", "category")
        conn.commit()
        flash(f"Đã thêm danh mục «{name}».", "success")
    except Exception:
        flash("Tên danh mục đã tồn tại.", "danger")
    conn.close()
    return redirect(url_for("admin_categories"))


@app.route("/admin/categories/<int:cat_id>/edit", methods=["POST"])
@login_required
@admin_required
def admin_category_edit(cat_id):
    name  = request.form.get("name", "").strip()
    icon  = request.form.get("icon", "📦").strip()
    order = request.form.get("sort_order", "99").strip()
    if not name:
        flash("Tên không được để trống.", "danger")
        return redirect(url_for("admin_categories"))
    conn = connect_db()
    conn.execute("UPDATE categories SET name=?, icon=?, sort_order=? WHERE id=?",
                 (name, icon, int(order) if order.isdigit() else 99, cat_id))
    log_admin_action(conn, f"Sửa danh mục #{cat_id} → {name}", "category", cat_id)
    conn.commit()
    conn.close()
    flash("Đã cập nhật danh mục.", "success")
    return redirect(url_for("admin_categories"))


@app.route("/admin/categories/<int:cat_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_category_delete(cat_id):
    conn = connect_db()
    cat = conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
    if cat:
        conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        log_admin_action(conn, f"Xóa danh mục #{cat_id}: {cat['name']}", "category", cat_id)
        conn.commit()
        flash(f"Đã xóa danh mục «{cat['name']}».", "success")
    conn.close()
    return redirect(url_for("admin_categories"))


# =========================
# ADMIN: PROFILE & QUẢN LÝ USER NÂNG CAO
# =========================
@app.route("/admin/users/<int:user_id>/profile")
@login_required
@admin_required
def admin_user_profile(user_id):
    conn = connect_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        flash("Không tìm thấy người dùng.", "danger")
        return redirect(url_for("admin_users"))
    posts = conn.execute("""
        SELECT * FROM posts WHERE user_id=? ORDER BY id DESC
    """, (user_id,)).fetchall()
    payments = conn.execute("""
        SELECT py.*, p.title FROM payments py
        LEFT JOIN posts p ON py.post_id=p.id
        WHERE py.user_id=? ORDER BY py.id DESC
    """, (user_id,)).fetchall()
    claims = conn.execute("""
        SELECT c.*, p.title as found_title FROM claims c
        LEFT JOIN posts p ON c.found_post_id=p.id
        WHERE c.claimer_user_id=? ORDER BY c.id DESC
    """, (user_id,)).fetchall()
    stats = {
        "total_posts":    conn.execute("SELECT COUNT(*) as c FROM posts WHERE user_id=?", (user_id,)).fetchone()["c"],
        "active_posts":   conn.execute("SELECT COUNT(*) as c FROM posts WHERE user_id=? AND status='active'", (user_id,)).fetchone()["c"],
        "resolved_posts": conn.execute("SELECT COUNT(*) as c FROM posts WHERE user_id=? AND status='resolved'", (user_id,)).fetchone()["c"],
        "total_claims":   conn.execute("SELECT COUNT(*) as c FROM claims WHERE claimer_user_id=?", (user_id,)).fetchone()["c"],
        "total_paid":     conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM payments WHERE user_id=? AND status='paid'", (user_id,)).fetchone()["s"],
    }
    conn.close()
    return render_template("admin_user_profile.html", user=user, posts=posts,
                           payments=payments, claims=claims, stats=stats)


@app.route("/admin/users/<int:user_id>/edit", methods=["POST"])
@login_required
@admin_required
def admin_user_edit(user_id):
    full_name = request.form.get("full_name", "").strip()
    email     = request.form.get("email", "").strip().lower() or None
    role      = request.form.get("role", "user").strip()
    if role not in ("user", "moderator", "admin"):
        role = "user"
    if not full_name:
        flash("Họ tên không được để trống.", "danger")
        return redirect(url_for("admin_user_profile", user_id=user_id))
    if role == "admin" and user_id == session["user_id"]:
        pass  # allow editing own info
    conn = connect_db()
    conn.execute("UPDATE users SET full_name=?, email=?, role=? WHERE id=?",
                 (full_name, email, role, user_id))
    log_admin_action(conn, f"Sửa thông tin user #{user_id}", "user", user_id,
                     f"name={full_name}, email={email}, role={role}")
    conn.commit()
    conn.close()
    flash("Đã cập nhật thông tin người dùng.", "success")
    return redirect(url_for("admin_user_profile", user_id=user_id))


@app.route("/admin/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@admin_required
def admin_reset_password(user_id):
    new_pass = request.form.get("new_password", "").strip()
    force_change = 1 if request.form.get("force_change") else 0
    if len(new_pass) < 6:
        flash("Mật khẩu mới phải có ít nhất 6 ký tự.", "danger")
        return redirect(url_for("admin_user_profile", user_id=user_id))
    conn = connect_db()
    user = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    conn.execute("UPDATE users SET password=?, force_password_change=? WHERE id=?",
                 (generate_password_hash(new_pass), force_change, user_id))
    log_admin_action(conn, f"Reset mật khẩu user #{user_id} @{user['username'] if user else '?'}", "user", user_id)
    conn.commit()
    conn.close()
    flash("Đã đặt lại mật khẩu thành công.", "success")
    return redirect(url_for("admin_user_profile", user_id=user_id))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    if user_id == session["user_id"]:
        flash("Bạn không thể xóa tài khoản của chính mình.", "danger")
        return redirect(url_for("admin_users"))
    handle_posts = request.form.get("handle_posts", "keep")
    conn = connect_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        flash("Không tìm thấy người dùng.", "danger")
        return redirect(url_for("admin_users"))
    if handle_posts == "delete":
        post_ids = [r["id"] for r in conn.execute("SELECT id FROM posts WHERE user_id=?", (user_id,)).fetchall()]
        for pid in post_ids:
            conn.execute("DELETE FROM claims WHERE found_post_id=? OR lost_post_id=?", (pid, pid))
            conn.execute("DELETE FROM payments WHERE post_id=?", (pid,))
        conn.execute("DELETE FROM posts WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM claims WHERE claimer_user_id=?", (user_id,))
    conn.execute("DELETE FROM comments WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    log_admin_action(conn, f"Xóa tài khoản #{user_id} @{user['username']}", "user", user_id,
                     f"handle_posts={handle_posts}")
    conn.commit()
    conn.close()
    flash(f"Đã xóa tài khoản @{user['username']}.", "success")
    return redirect(url_for("admin_users"))


# =========================
# ADMIN: DUYỆT HÀNG LOẠT
# =========================
@app.route("/admin/posts/bulk", methods=["POST"])
@login_required
@admin_required
def admin_bulk_posts():
    action   = request.form.get("action", "")
    post_ids = request.form.getlist("post_ids")
    if not post_ids:
        flash("Chưa chọn bài đăng nào.", "warning")
        return redirect(url_for("admin_posts"))
    valid_ids = [int(p) for p in post_ids if p.isdigit()]
    if not valid_ids:
        flash("Danh sách bài không hợp lệ.", "danger")
        return redirect(url_for("admin_posts"))
    conn = connect_db()
    count = len(valid_ids)
    placeholders = ",".join("?" * count)
    if action == "approve":
        for pid in valid_ids:
            post = conn.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
            if post and post["status"] == "pending_review":
                conn.execute("UPDATE posts SET status='active', vip_started_at=NULL, vip_expires_at=NULL WHERE id=?", (pid,))
        log_admin_action(conn, f"Duyệt hàng loạt {count} bài", "post", None, str(valid_ids))
        flash(f"Đã duyệt {count} bài đăng.", "success")
    elif action == "reject":
        conn.execute(f"UPDATE posts SET status='rejected' WHERE id IN ({placeholders})", valid_ids)
        log_admin_action(conn, f"Từ chối hàng loạt {count} bài", "post", None, str(valid_ids))
        flash(f"Đã từ chối {count} bài đăng.", "warning")
    elif action == "hide":
        conn.execute(f"UPDATE posts SET status='hidden' WHERE id IN ({placeholders})", valid_ids)
        log_admin_action(conn, f"Ẩn hàng loạt {count} bài", "post", None, str(valid_ids))
        flash(f"Đã ẩn {count} bài đăng.", "warning")
    elif action == "delete":
        for pid in valid_ids:
            conn.execute("DELETE FROM claims WHERE found_post_id=? OR lost_post_id=?", (pid, pid))
            conn.execute("DELETE FROM payments WHERE post_id=?", (pid,))
        conn.execute(f"DELETE FROM posts WHERE id IN ({placeholders})", valid_ids)
        log_admin_action(conn, f"Xóa hàng loạt {count} bài", "post", None, str(valid_ids))
        flash(f"Đã xóa {count} bài đăng.", "info")
    elif action == "resolve":
        conn.execute(f"UPDATE posts SET status='resolved' WHERE id IN ({placeholders})", valid_ids)
        log_admin_action(conn, f"Đánh dấu resolved hàng loạt {count} bài", "post", None, str(valid_ids))
        flash(f"Đã đánh dấu {count} bài là đã xử lý.", "success")
    else:
        flash("Hành động không hợp lệ.", "danger")
    conn.commit()
    conn.close()
    return redirect(url_for("admin_posts"))


# =========================
# ADMIN: GHIM BÀI
# =========================
@app.route("/admin/post/<int:post_id>/pin", methods=["POST"])
@login_required
@admin_required
def admin_pin_post(post_id):
    expires_input = request.form.get("pin_expires_at", "").strip()
    pin_until = None
    if expires_input:
        try:
            pin_until = str(datetime.fromisoformat(expires_input))
        except ValueError:
            pass
    conn = connect_db()
    conn.execute("UPDATE posts SET is_pinned=1, pin_expires_at=? WHERE id=?", (pin_until, post_id))
    log_admin_action(conn, f"Ghim bài #{post_id}", "post", post_id, f"hết hạn: {pin_until or 'không giới hạn'}")
    conn.commit()
    conn.close()
    flash(f"Đã ghim bài #{post_id}.", "success")
    return redirect(url_for("admin_posts"))


@app.route("/admin/post/<int:post_id>/unpin", methods=["POST"])
@login_required
@admin_required
def admin_unpin_post(post_id):
    conn = connect_db()
    conn.execute("UPDATE posts SET is_pinned=0, pin_expires_at=NULL WHERE id=?", (post_id,))
    log_admin_action(conn, f"Bỏ ghim bài #{post_id}", "post", post_id)
    conn.commit()
    conn.close()
    flash(f"Đã bỏ ghim bài #{post_id}.", "info")
    return redirect(url_for("admin_posts"))


# =========================
# ADMIN: NHÃN BÀI ĐĂNG
# =========================
@app.route("/admin/post/<int:post_id>/label", methods=["POST"])
@login_required
@admin_required
def admin_post_label(post_id):
    label = request.form.get("label", "").strip() or None
    conn = connect_db()
    conn.execute("UPDATE posts SET label=? WHERE id=?", (label, post_id))
    log_admin_action(conn, f"Gắn nhãn bài #{post_id}: {label or 'xóa nhãn'}", "post", post_id)
    conn.commit()
    conn.close()
    flash("Đã cập nhật nhãn.", "success")
    return redirect(url_for("admin_posts"))


# =========================
# ADMIN: TẶNG VIP THỦ CÔNG
# =========================
@app.route("/admin/vip/grant", methods=["POST"])
@login_required
@admin_required
def admin_vip_grant():
    post_id  = request.form.get("post_id", "").strip()
    pkg_key  = request.form.get("package_key", "").strip()
    reason   = request.form.get("reason", "Admin tặng").strip()
    pkgs = get_vip_packages()
    if not post_id or pkg_key not in pkgs:
        flash("Thông tin không hợp lệ.", "danger")
        return redirect(url_for("admin_posts"))
    conn = connect_db()
    post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        conn.close()
        flash("Không tìm thấy bài đăng.", "danger")
        return redirect(url_for("admin_posts"))
    pkg = pkgs[pkg_key]
    now = datetime.now()
    vip_start = str(now)
    vip_end = str(now + timedelta(days=pkg["days"]))
    conn.execute("""
        UPDATE posts SET package_key=?, priority=?, vip_started_at=?, vip_expires_at=? WHERE id=?
    """, (pkg_key, pkg["priority"], vip_start, vip_end, post_id))
    conn.execute("""
        INSERT INTO payments (user_id, post_id, package_key, package_name, amount,
            transfer_content, status, created_at, confirmed_at)
        VALUES (?, ?, ?, ?, 0, ?, 'paid', ?, ?)
    """, (post["user_id"], post_id, pkg_key, pkg["name"],
          f"ADMIN_GRANT {reason}", str(now), str(now)))
    log_admin_action(conn, f"Tặng VIP {pkg['name']} cho bài #{post_id}", "post", int(post_id),
                     f"Lý do: {reason}")
    conn.commit()
    conn.close()
    flash(f"Đã tặng VIP {pkg['name']} cho bài #{post_id}.", "success")
    return redirect(url_for("admin_posts"))


# =========================
# ADMIN: THÔNG BÁO HỆ THỐNG
# =========================
@app.route("/admin/announcements")
@login_required
@admin_required
def admin_announcements():
    conn = connect_db()
    anns = conn.execute("""
        SELECT a.*, u.full_name FROM announcements a
        LEFT JOIN users u ON a.created_by=u.id
        ORDER BY a.id DESC
    """).fetchall()
    conn.close()
    return render_template("admin_announcements.html", announcements=anns)


@app.route("/admin/announcements/add", methods=["POST"])
@login_required
@admin_required
def admin_announcement_add():
    title      = request.form.get("title", "").strip()
    content    = request.form.get("content", "").strip()
    ann_type   = request.form.get("type", "info").strip()
    show_from  = request.form.get("show_from", "").strip() or None
    show_until = request.form.get("show_until", "").strip() or None
    if not title:
        flash("Tiêu đề không được để trống.", "danger")
        return redirect(url_for("admin_announcements"))
    conn = connect_db()
    conn.execute("""
        INSERT INTO announcements (title, content, type, show_from, show_until, is_active, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
    """, (title, content, ann_type, show_from, show_until, str(datetime.now()), session["user_id"]))
    log_admin_action(conn, f"Thêm thông báo: {title}", "announcement")
    conn.commit()
    conn.close()
    flash("Đã thêm thông báo.", "success")
    return redirect(url_for("admin_announcements"))


@app.route("/admin/announcements/<int:ann_id>/toggle", methods=["POST"])
@login_required
@admin_required
def admin_announcement_toggle(ann_id):
    conn = connect_db()
    ann = conn.execute("SELECT * FROM announcements WHERE id=?", (ann_id,)).fetchone()
    if ann:
        new_val = 0 if ann["is_active"] else 1
        conn.execute("UPDATE announcements SET is_active=? WHERE id=?", (new_val, ann_id))
        log_admin_action(conn, f"{'Bật' if new_val else 'Tắt'} thông báo #{ann_id}", "announcement", ann_id)
        conn.commit()
    conn.close()
    flash("Đã cập nhật trạng thái thông báo.", "success")
    return redirect(url_for("admin_announcements"))


@app.route("/admin/announcements/<int:ann_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_announcement_delete(ann_id):
    conn = connect_db()
    conn.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    log_admin_action(conn, f"Xóa thông báo #{ann_id}", "announcement", ann_id)
    conn.commit()
    conn.close()
    flash("Đã xóa thông báo.", "info")
    return redirect(url_for("admin_announcements"))


# =========================
# ADMIN: QUẢN LÝ BÌNH LUẬN
# =========================
@app.route("/admin/comments")
@login_required
@admin_required
def admin_comments_list():
    page = request.args.get("page", 1, type=int) or 1
    per_page = 30
    offset = (page - 1) * per_page
    conn = connect_db()
    total = conn.execute("SELECT COUNT(*) as c FROM comments").fetchone()["c"]
    comments = conn.execute("""
        SELECT c.*, u.full_name, u.username, p.title as post_title
        FROM comments c
        LEFT JOIN users u ON c.user_id=u.id
        LEFT JOIN posts p ON c.post_id=p.id
        ORDER BY c.id DESC LIMIT ? OFFSET ?
    """, (per_page, offset)).fetchall()
    banned_words = conn.execute("SELECT * FROM banned_words ORDER BY id DESC").fetchall()
    conn.close()
    total_pages = (total + per_page - 1) // per_page
    return render_template("admin_comments.html", comments=comments,
                           banned_words=banned_words,
                           page=page, total_pages=total_pages, total=total)


@app.route("/admin/comments/<int:comment_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_comment(comment_id):
    conn = connect_db()
    comment = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
    if comment:
        conn.execute("DELETE FROM comments WHERE id=?", (comment_id,))
        log_admin_action(conn, f"Admin xóa bình luận #{comment_id}", "comment", comment_id,
                         f"Post #{comment['post_id']}: {comment['content'][:50]}")
        conn.commit()
        flash("Đã xóa bình luận.", "success")
    conn.close()
    return redirect(url_for("admin_comments_list"))


# =========================
# ADMIN REPORTS
# =========================
@app.route("/admin/reports")
@login_required
@admin_required
def admin_reports():
    conn = connect_db()
    status_filter = request.args.get("status", "pending")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20

    total = conn.execute(
        "SELECT COUNT(*) as c FROM reports WHERE status=?", (status_filter,)
    ).fetchone()["c"]
    total_pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page

    reports = conn.execute("""
        SELECT r.*, u.full_name as reporter_name, u.username as reporter_username,
               p.title as post_title
        FROM reports r
        LEFT JOIN users u ON r.reporter_user_id = u.id
        LEFT JOIN posts p ON r.post_id = p.id
        WHERE r.status = ?
        ORDER BY r.id DESC
        LIMIT ? OFFSET ?
    """, (status_filter, per_page, offset)).fetchall()
    conn.close()
    return render_template("admin_reports.html",
                           reports=reports,
                           status_filter=status_filter,
                           page=page,
                           total_pages=total_pages,
                           total=total)


@app.route("/admin/reports/<int:report_id>/approve", methods=["POST"])
@login_required
@admin_required
def admin_approve_report(report_id):
    admin_note = request.form.get("admin_note", "").strip()
    conn = connect_db()
    report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if report:
        conn.execute(
            "UPDATE reports SET status='approved', admin_note=?, reviewed_at=?, reviewed_by=? WHERE id=?",
            (admin_note, str(datetime.now()), session["user_id"], report_id)
        )
        conn.execute(
            "UPDATE posts SET is_scam_warned=1 WHERE id=?", (report["post_id"],)
        )
        log_admin_action(conn, f"Duyệt report #{report_id} — bài #{report['post_id']}", "report", report_id)
        conn.commit()
        flash("Đã duyệt báo cáo. Bài đăng bị gắn cảnh báo lừa đảo.", "success")
    conn.close()
    return redirect(url_for("admin_reports", status="pending"))


@app.route("/admin/reports/<int:report_id>/reject", methods=["POST"])
@login_required
@admin_required
def admin_reject_report(report_id):
    admin_note = request.form.get("admin_note", "").strip()
    conn = connect_db()
    report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if report:
        conn.execute(
            "UPDATE reports SET status='rejected', admin_note=?, reviewed_at=?, reviewed_by=? WHERE id=?",
            (admin_note, str(datetime.now()), session["user_id"], report_id)
        )
        log_admin_action(conn, f"Từ chối report #{report_id}", "report", report_id)
        conn.commit()
        flash("Đã từ chối báo cáo.", "warning")
    conn.close()
    return redirect(url_for("admin_reports", status="pending"))


@app.route("/admin/banned-words/add", methods=["POST"])
@login_required
@admin_required
def admin_banned_word_add():
    word = request.form.get("word", "").strip().lower()
    if not word:
        flash("Từ cần thêm không được để trống.", "danger")
        return redirect(url_for("admin_comments_list"))
    conn = connect_db()
    try:
        conn.execute("INSERT INTO banned_words (word, created_at) VALUES (?, ?)",
                     (word, str(datetime.now())))
        log_admin_action(conn, f"Thêm từ cấm: {word}", "banned_word")
        conn.commit()
        flash(f"Đã thêm từ cấm «{word}».", "success")
    except Exception:
        flash("Từ này đã có trong danh sách.", "warning")
    conn.close()
    return redirect(url_for("admin_comments_list"))


@app.route("/admin/banned-words/<int:word_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_banned_word_delete(word_id):
    conn = connect_db()
    bw = conn.execute("SELECT word FROM banned_words WHERE id=?", (word_id,)).fetchone()
    conn.execute("DELETE FROM banned_words WHERE id=?", (word_id,))
    log_admin_action(conn, f"Xóa từ cấm #{word_id}: {bw['word'] if bw else '?'}", "banned_word", word_id)
    conn.commit()
    conn.close()
    flash("Đã xóa từ cấm.", "info")
    return redirect(url_for("admin_comments_list"))


# =========================
# ADMIN: VOUCHER / MÃ GIẢM GIÁ
# =========================
@app.route("/admin/vouchers")
@login_required
@admin_required
def admin_vouchers():
    conn = connect_db()
    vouchers = conn.execute("SELECT * FROM vouchers ORDER BY id DESC").fetchall()
    conn.close()
    pkgs = get_vip_packages()
    return render_template("admin_vouchers.html", vouchers=vouchers, vip_packages=pkgs)


@app.route("/admin/vouchers/add", methods=["POST"])
@login_required
@admin_required
def admin_voucher_add():
    code           = request.form.get("code", "").strip().upper()
    discount_type  = request.form.get("discount_type", "percent")
    discount_value = request.form.get("discount_value", "0").strip()
    max_uses       = request.form.get("max_uses", "0").strip()
    valid_from     = request.form.get("valid_from", "").strip() or None
    valid_until    = request.form.get("valid_until", "").strip() or None
    applicable     = ",".join(request.form.getlist("applicable_packages")) or None
    note           = request.form.get("note", "").strip()
    if not code or not discount_value.isdigit():
        flash("Mã và giá trị giảm không được để trống.", "danger")
        return redirect(url_for("admin_vouchers"))
    conn = connect_db()
    try:
        conn.execute("""
            INSERT INTO vouchers (code, discount_type, discount_value, max_uses, valid_from, valid_until,
                applicable_packages, is_active, created_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (code, discount_type, int(discount_value), int(max_uses) if max_uses.isdigit() else 0,
              valid_from, valid_until, applicable, str(datetime.now()), note))
        log_admin_action(conn, f"Thêm voucher {code}", "voucher")
        conn.commit()
        flash(f"Đã thêm voucher «{code}».", "success")
    except Exception:
        flash("Mã voucher đã tồn tại.", "danger")
    conn.close()
    return redirect(url_for("admin_vouchers"))


@app.route("/admin/vouchers/<int:voucher_id>/toggle", methods=["POST"])
@login_required
@admin_required
def admin_voucher_toggle(voucher_id):
    conn = connect_db()
    v = conn.execute("SELECT * FROM vouchers WHERE id=?", (voucher_id,)).fetchone()
    if v:
        conn.execute("UPDATE vouchers SET is_active=? WHERE id=?", (0 if v["is_active"] else 1, voucher_id))
        log_admin_action(conn, f"Toggle voucher #{voucher_id}", "voucher", voucher_id)
        conn.commit()
    conn.close()
    return redirect(url_for("admin_vouchers"))


@app.route("/admin/vouchers/<int:voucher_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_voucher_delete(voucher_id):
    conn = connect_db()
    conn.execute("DELETE FROM vouchers WHERE id=?", (voucher_id,))
    log_admin_action(conn, f"Xóa voucher #{voucher_id}", "voucher", voucher_id)
    conn.commit()
    conn.close()
    flash("Đã xóa voucher.", "info")
    return redirect(url_for("admin_vouchers"))


# =========================
# ADMIN: HOÀN TIỀN
# =========================
@app.route("/admin/payments/<int:payment_id>/refund", methods=["POST"])
@login_required
@admin_required
def admin_payment_refund(payment_id):
    note = request.form.get("refund_note", "").strip()
    conn = connect_db()
    payment = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    if not payment:
        conn.close()
        flash("Không tìm thấy giao dịch.", "danger")
        return redirect(url_for("admin_payments"))
    conn.execute("UPDATE payments SET refunded=1, refund_note=? WHERE id=?", (note, payment_id))
    conn.execute("UPDATE posts SET priority=0, package_key=NULL, vip_started_at=NULL, vip_expires_at=NULL WHERE id=?",
                 (payment["post_id"],))
    log_admin_action(conn, f"Hoàn tiền payment #{payment_id}", "payment", payment_id,
                     f"Lý do: {note}")
    conn.commit()
    conn.close()
    flash(f"Đã đánh dấu hoàn tiền cho giao dịch #{payment_id}.", "success")
    return redirect(url_for("admin_payments"))


# =========================
# ADMIN: XUẤT CSV
# =========================
@app.route("/admin/export/revenue.csv")
@login_required
@admin_required
def admin_export_revenue_csv():
    from flask import Response
    from_dt = request.args.get("from", "")
    to_dt   = request.args.get("to", "")
    conn = connect_db()
    sql = """
        SELECT py.id, py.created_at, py.confirmed_at, py.amount, py.status,
               py.package_key, py.package_name, py.transfer_content,
               py.refunded, py.refund_note,
               u.username, u.full_name, u.email,
               p.title as post_title, p.id as post_id
        FROM payments py
        LEFT JOIN users u ON py.user_id=u.id
        LEFT JOIN posts p ON py.post_id=p.id
        WHERE 1=1
    """
    params = []
    if from_dt:
        sql += " AND date(py.created_at) >= ?"
        params.append(from_dt)
    if to_dt:
        sql += " AND date(py.created_at) <= ?"
        params.append(to_dt)
    sql += " ORDER BY py.id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    lines = ["ID,Ngày tạo,Ngày xác nhận,Số tiền,Trạng thái,Gói,Nội dung CK,Hoàn tiền,Lý do hoàn,Username,Họ tên,Email,Tiêu đề bài,Post ID"]
    for r in rows:
        lines.append(",".join(str(r[k] or "") for k in [
            "id", "created_at", "confirmed_at", "amount", "status",
            "package_name", "transfer_content", "refunded", "refund_note",
            "username", "full_name", "email", "post_title", "post_id"
        ]))
    csv_data = "\ufeff" + "\n".join(lines)
    log_admin_action(connect_db(), "Xuất CSV doanh thu", "export")
    return Response(
        csv_data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=revenue.csv"}
    )


# =========================
# ADMIN: API STATS (cho Chart.js)
# =========================
@app.route("/admin/api/stats")
@login_required
@admin_required
def admin_api_stats():
    from flask import jsonify
    period = request.args.get("period", "7days")
    conn = connect_db()
    if period == "30days":
        days = 30
    else:
        days = 7

    labels, posts_data, users_data, revenue_data = [], [], [], []
    for i in range(days - 1, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        labels.append(d[5:])
        posts_data.append(conn.execute(
            "SELECT COUNT(*) as c FROM posts WHERE date(created_at)=?", (d,)
        ).fetchone()["c"])
        users_data.append(conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE date(created_at)=?", (d,)
        ).fetchone()["c"])
        revenue_data.append(conn.execute(
            "SELECT COALESCE(SUM(amount),0) as s FROM payments WHERE status='paid' AND date(created_at)=?", (d,)
        ).fetchone()["s"])
    conn.close()
    return jsonify({"labels": labels, "posts": posts_data, "users": users_data, "revenue": revenue_data})


# =========================
# ADMIN: GỬI EMAIL HÀNG LOẠT
# =========================
@app.route("/admin/bulk-email", methods=["GET", "POST"])
@login_required
@admin_required
def admin_bulk_email():
    if request.method == "POST":
        subject   = request.form.get("subject", "").strip()
        html_body = request.form.get("html_body", "").strip()
        target    = request.form.get("target", "all")
        if not subject or not html_body:
            flash("Tiêu đề và nội dung không được để trống.", "danger")
            return redirect(url_for("admin_bulk_email"))
        conn = connect_db()
        if target == "all":
            recipients = conn.execute("SELECT email FROM users WHERE email IS NOT NULL AND email != ''").fetchall()
        elif target == "no_post":
            recipients = conn.execute("""
                SELECT u.email FROM users u
                LEFT JOIN posts p ON p.user_id=u.id
                WHERE u.email IS NOT NULL AND u.email != ''
                GROUP BY u.id HAVING COUNT(p.id)=0
            """).fetchall()
        else:
            recipients = conn.execute("SELECT email FROM users WHERE email IS NOT NULL AND email != ''").fetchall()
        count = 0
        for r in recipients:
            if r["email"]:
                send_email(r["email"], subject, html_body)
                count += 1
        log_admin_action(conn, f"Gửi email hàng loạt: {subject}", "bulk_email", None,
                         f"target={target}, count={count}")
        conn.commit()
        conn.close()
        flash(f"Đã gửi email tới {count} người dùng (chạy nền).", "success")
        return redirect(url_for("admin_bulk_email"))
    return render_template("admin_bulk_email.html")


# =========================
# API: KIỂM TRA VOUCHER
# =========================
@app.route("/api/voucher/check", methods=["POST"])
@login_required
def check_voucher():
    from flask import jsonify
    code = request.form.get("code", "").strip().upper()
    pkg  = request.form.get("package_key", "").strip()
    if not code:
        return jsonify({"valid": False, "message": "Nhập mã voucher"})
    conn = connect_db()
    v = conn.execute("""
        SELECT * FROM vouchers WHERE code=? AND is_active=1
        AND (valid_from IS NULL OR valid_from <= ?)
        AND (valid_until IS NULL OR valid_until >= ?)
    """, (code, str(datetime.now()), str(datetime.now()))).fetchone()
    conn.close()
    if not v:
        return jsonify({"valid": False, "message": "Mã không hợp lệ hoặc đã hết hạn"})
    if v["max_uses"] > 0 and v["used_count"] >= v["max_uses"]:
        return jsonify({"valid": False, "message": "Mã đã hết lượt sử dụng"})
    if v["applicable_packages"] and pkg and pkg not in v["applicable_packages"].split(","):
        return jsonify({"valid": False, "message": "Mã không áp dụng cho gói này"})
    pkgs = get_vip_packages()
    original = pkgs.get(pkg, {}).get("price", 0) if pkg else 0
    if v["discount_type"] == "percent":
        discount = int(original * v["discount_value"] / 100)
    else:
        discount = v["discount_value"]
    final_price = max(0, original - discount)
    return jsonify({
        "valid": True,
        "message": f"Giảm {'{}%'.format(v['discount_value']) if v['discount_type']=='percent' else '{:,}đ'.format(v['discount_value'])}",
        "discount_type": v["discount_type"],
        "discount_value": v["discount_value"],
        "final_price": final_price,
        "original_price": original,
    })


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, host="127.0.0.1", port=5000)
