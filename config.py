import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
SESSION_DIR = os.path.join(BASE_DIR, "flask_sessions")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
PER_PAGE = 12

VIP_PACKAGES = {
    "goi_1": {"name": "Nổi bật",  "price": 10000,  "priority": 1, "label": "NỔI BẬT", "days": 3},
    "goi_2": {"name": "Ưu tiên",  "price": 20000,  "priority": 2, "label": "ƯU TIÊN", "days": 5},
    "goi_3": {"name": "Tìm gấp",  "price": 30000,  "priority": 3, "label": "TÌM GẤP", "days": 10},
}
