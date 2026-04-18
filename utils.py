import os
import unicodedata
import secrets as _secrets
from datetime import datetime
from werkzeug.utils import secure_filename
from config import ALLOWED_EXTENSIONS, UPLOAD_FOLDER

try:
    from PIL import Image as _PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def normalize_vn(text: str) -> str:
    """Chuyển tiếng Việt có dấu → không dấu, viết thường."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower()


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
    save_ext = ext.lower() if ext.lower() == ".gif" else ".jpg"
    filename = f"{name}_{int(datetime.now().timestamp())}{save_ext}"
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
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


def check_banned_words(conn, *texts):
    """Trả về từ cấm đầu tiên tìm thấy, hoặc None."""
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


def log_admin_action(conn, action, target_type=None, target_id=None, detail=None):
    from flask import session
    try:
        conn.execute(
            "INSERT INTO admin_logs (admin_id, admin_username, action, target_type, target_id, detail, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (session.get("user_id"), session.get("username", "admin"),
             action, target_type, target_id, detail, str(datetime.now()))
        )
    except Exception:
        pass


def match_score(lost_post, found_post):
    """Chấm điểm rule-based fallback."""
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
    keys_l = lost_post.keys() if hasattr(lost_post, "keys") else {}
    keys_f = found_post.keys() if hasattr(found_post, "keys") else {}
    lost_tags  = set(t.strip() for t in (lost_post["tags"] or "" if "tags" in keys_l else "").split(",") if t.strip())
    found_tags = set(t.strip() for t in (found_post["tags"] or "" if "tags" in keys_f else "").split(",") if t.strip())
    score += len(lost_tags & found_tags) * 5
    return min(score, 100)


def downgrade_expired_priorities(conn=None):
    from database import connect_db as _connect
    _conn = conn or _connect()
    try:
        _conn.execute("""
            UPDATE posts SET priority=0, package_key=NULL
            WHERE priority>0 AND vip_expires_at IS NOT NULL
            AND vip_expires_at < datetime('now','localtime')
        """)
        _conn.commit()
    except Exception:
        pass
    if conn is None:
        _conn.close()


def time_ago(date_str):
    if not date_str:
        return "Không rõ"
    try:
        dt = datetime.fromisoformat(str(date_str)[:19])
        delta = datetime.now() - dt
        total_seconds = int(delta.total_seconds())
        if total_seconds < 3600:
            mins = max(1, total_seconds // 60)
            return f"{mins} phút trước"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            return f"{hours} giờ trước"
        else:
            return f"{delta.days} ngày trước"
    except Exception:
        return str(date_str)[:10]


def generate_email_token():
    return _secrets.token_urlsafe(32)
