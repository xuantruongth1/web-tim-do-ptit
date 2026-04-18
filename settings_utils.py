from datetime import datetime
from database import connect_db
from config import VIP_PACKAGES


def get_setting(key, default=""):
    conn = connect_db()
    row = conn.execute("SELECT value FROM site_settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = connect_db()
    conn.execute(
        "INSERT OR REPLACE INTO site_settings (key, value, updated_at) VALUES (?,?,?)",
        (key, value, str(datetime.now()))
    )
    conn.commit()
    conn.close()


def get_all_settings():
    conn = connect_db()
    rows = conn.execute("SELECT key, value FROM site_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


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
    return packages or VIP_PACKAGES
