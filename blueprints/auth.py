"""Routes: register, verify_email, login, logout, change_password_forced."""
import os
from datetime import datetime
from flask import request, session, flash, redirect, url_for, render_template
from werkzeug.security import generate_password_hash, check_password_hash
from database import connect_db
from decorators import login_required
from email_utils import send_email
from utils import generate_email_token


def register_routes(app, _rate):

    @app.route("/register", methods=["GET", "POST"])
    @_rate("5 per minute")
    def register():
        if request.method == "POST":
            full_name = request.form["full_name"].strip()
            username  = request.form["username"].strip()
            password  = request.form["password"].strip()
            email     = request.form.get("email", "").strip().lower() or None

            if len(password) < 6:
                flash("Mật khẩu phải có ít nhất 6 ký tự.", "danger")
                return redirect(url_for("register"))

            conn = connect_db()
            if conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
                conn.close()
                flash("Tên đăng nhập đã tồn tại.", "danger")
                return redirect(url_for("register"))

            token = generate_email_token() if email else None
            conn.execute(
                "INSERT INTO users (full_name, username, password, role, created_at, email, email_verified, email_token) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (full_name, username, generate_password_hash(password),
                 "user", str(datetime.now()), email, 0, token)
            )
            conn.commit()
            conn.close()

            if email and token:
                verify_url = request.host_url.rstrip("/") + url_for("verify_email", token=token)
                send_email(email, "Xác minh email — PTIT Lost & Found",
                    f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;background:#f8fafc;border-radius:12px;">
                    <h2 style="color:#16a34a;">Xác minh địa chỉ email</h2>
                    <p>Xin chào <strong>{full_name}</strong>,</p>
                    <p>Tài khoản <strong>@{username}</strong> đã được tạo. Nhấn nút bên dưới để xác minh email.</p>
                    <a href="{verify_url}" style="display:inline-block;margin-top:12px;padding:10px 24px;background:#16a34a;color:white;border-radius:8px;text-decoration:none;font-weight:700;">Xác minh email →</a>
                    <p style="margin-top:16px;font-size:12px;color:#94a3b8;">Nếu bạn không đăng ký, hãy bỏ qua email này.</p>
                    </div>""")
            admin_email = os.environ.get("MAIL_USERNAME", "")
            if admin_email:
                send_email(admin_email, f"Người dùng mới đăng ký: @{username}",
                    f"<p>Người dùng mới: <strong>{full_name}</strong> (@{username}), email: {email or 'Không có'}</p>")
            flash(
                "Đăng ký thành công! Hãy kiểm tra email để xác minh tài khoản, sau đó đăng nhập." if email
                else "Đăng ký thành công, hãy đăng nhập.", "success"
            )
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
            session["user_id"]  = user["id"]
            session["full_name"] = user["full_name"]
            session["username"] = user["username"]
            session["role"]     = user["role"]
            session["avatar"]   = user["avatar"] or ""
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
            conn.execute(
                "UPDATE users SET password=?, force_password_change=0 WHERE id=?",
                (generate_password_hash(new_pass), session["user_id"])
            )
            conn.commit()
            conn.close()
            flash("Đã đổi mật khẩu thành công.", "success")
            return redirect(url_for("home"))
        return render_template("change_password_forced.html")
