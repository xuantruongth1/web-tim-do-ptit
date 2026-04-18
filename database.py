import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash
from config import DB_PATH


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    from utils import normalize_vn
    conn.create_function("norm_vn", 1, normalize_vn)
    return conn


def create_tables():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        created_at TEXT NOT NULL
    )""")

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
    )""")

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
    )""")

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
    )""")
    conn.commit()

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
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS site_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        icon TEXT,
        sort_order INTEGER DEFAULT 0,
        created_at TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        type TEXT NOT NULL DEFAULT 'info',
        show_from TEXT,
        show_until TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        created_by INTEGER
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS banned_words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT NOT NULL UNIQUE,
        created_at TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        reporter_user_id INTEGER NOT NULL,
        content TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        admin_note TEXT,
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewed_by INTEGER
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vouchers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        discount_type TEXT NOT NULL DEFAULT 'percent',
        discount_value INTEGER NOT NULL DEFAULT 0,
        max_uses INTEGER DEFAULT 0,
        used_count INTEGER DEFAULT 0,
        valid_from TEXT,
        valid_until TEXT,
        applicable_packages TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        note TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(post_id) REFERENCES posts(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

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
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL DEFAULT 'comment',
        message TEXT NOT NULL,
        link TEXT,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    conn.commit()

    # Migrations
    migrations = [
        "ALTER TABLE users ADD COLUMN is_locked INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN email TEXT",
        "ALTER TABLE claims ADD COLUMN owner_confirmed INTEGER DEFAULT 0",
        "ALTER TABLE claims ADD COLUMN contact_unlocked INTEGER DEFAULT 0",
        "ALTER TABLE claims ADD COLUMN owner_reviewed_at TEXT",
        "ALTER TABLE claims ADD COLUMN ai_reason TEXT",
        "ALTER TABLE posts ADD COLUMN verification_hint TEXT",
        "ALTER TABLE posts ADD COLUMN private_verification_note TEXT",
        "ALTER TABLE posts ADD COLUMN package_key TEXT",
        "ALTER TABLE posts ADD COLUMN vip_started_at TEXT",
        "ALTER TABLE posts ADD COLUMN vip_expires_at TEXT",
        "ALTER TABLE posts ADD COLUMN city TEXT",
        "ALTER TABLE posts ADD COLUMN campus TEXT",
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
        "ALTER TABLE users ADD COLUMN avatar TEXT",
        "ALTER TABLE users ADD COLUMN bio TEXT",
    ]
    for sql in migrations:
        try:
            cursor.execute(sql)
        except Exception:
            pass
    conn.commit()

    # Seed default categories
    count = cursor.execute("SELECT COUNT(*) as c FROM categories").fetchone()["c"]
    if count == 0:
        default_cats = [
            ("CCCD / Thẻ SV", "🪪", 1), ("Ví / Túi", "👜", 2), ("Chìa khóa", "🔑", 3),
            ("Điện thoại", "📱", 4), ("Thẻ xe", "🎫", 5), ("Laptop / Máy tính", "💻", 6),
            ("Quần áo", "👕", 7), ("Sách / Vở", "📚", 8), ("Tai nghe", "🎧", 9),
            ("Đồ dùng học tập", "✏️", 10), ("Trang sức / Phụ kiện", "💍", 11), ("Khác", "📦", 12),
        ]
        for name, icon, order in default_cats:
            try:
                cursor.execute(
                    "INSERT INTO categories (name, icon, sort_order, created_at) VALUES (?,?,?,?)",
                    (name, icon, order, str(datetime.now()))
                )
            except Exception:
                pass
        conn.commit()

    # Tạo admin mặc định
    admin = cursor.execute("SELECT * FROM users WHERE username=?", ("admin",)).fetchone()
    if not admin:
        cursor.execute(
            "INSERT INTO users (full_name, username, password, role, created_at) VALUES (?,?,?,?,?)",
            ("Quản trị viên", "admin", generate_password_hash("admin123"), "admin", str(datetime.now()))
        )
        conn.commit()

    conn.close()
