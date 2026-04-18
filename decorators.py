from functools import wraps
from flask import session, flash, redirect, url_for


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


def moderator_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if session.get("role") not in ("admin", "moderator"):
            flash("Bạn không có quyền truy cập.", "danger")
            return redirect(url_for("home"))
        return view_func(*args, **kwargs)
    return wrapper
