"""Routes: profile, my_posts, resolve_post, delete_post,
           update_profile, change_password, upload_avatar, resend_verify."""
import os
from datetime import datetime
from flask import request, session, flash, redirect, url_for, render_template, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from database import connect_db
from decorators import login_required
from utils import allowed_file, generate_email_token
from email_utils import send_email
from config import UPLOAD_FOLDER


def register_routes(app, _rate):

    @app.route("/profile")
    @login_required
    def profile():
        conn = connect_db()
        user  = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        stats = {
            "total":       conn.execute("SELECT COUNT(*) as c FROM posts WHERE user_id=?", (session["user_id"],)).fetchone()["c"],
            "active":      conn.execute("SELECT COUNT(*) as c FROM posts WHERE user_id=? AND status='active'", (session["user_id"],)).fetchone()["c"],
            "resolved":    conn.execute("SELECT COUNT(*) as c FROM posts WHERE user_id=? AND status='resolved'", (session["user_id"],)).fetchone()["c"],
            "claims_sent": conn.execute("SELECT COUNT(*) as c FROM claims WHERE claimer_user_id=?", (session["user_id"],)).fetchone()["c"],
        }
        conn.close()
        return render_template("profile.html", user=user, stats=stats)


    @app.route("/profile/update", methods=["POST"])
    @login_required
    def update_profile():
        full_name = request.form.get("full_name", "").strip()
        email     = request.form.get("email", "").strip().lower() or None
        bio       = request.form.get("bio", "").strip()[:300]

        if not full_name:
            return jsonify({"ok": False, "msg": "Họ tên không được để trống."})

        conn = connect_db()
        user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

        email_changed = (email or "") != (user["email"] or "")
        new_token = None

        if email_changed and email:
            # Kiểm tra email chưa dùng bởi người khác
            existing = conn.execute(
                "SELECT id FROM users WHERE email=? AND id!=?", (email, session["user_id"])
            ).fetchone()
            if existing:
                conn.close()
                return jsonify({"ok": False, "msg": "Email này đã được dùng bởi tài khoản khác."})
            new_token = generate_email_token()

        if email_changed and email:
            conn.execute(
                "UPDATE users SET full_name=?, email=?, email_verified=0, email_token=?, bio=? WHERE id=?",
                (full_name, email, new_token, bio, session["user_id"])
            )
        elif email_changed and not email:
            conn.execute(
                "UPDATE users SET full_name=?, email=NULL, email_verified=0, email_token=NULL, bio=? WHERE id=?",
                (full_name, bio, session["user_id"])
            )
        else:
            conn.execute(
                "UPDATE users SET full_name=?, bio=? WHERE id=?",
                (full_name, bio, session["user_id"])
            )
        conn.commit()
        conn.close()

        session["full_name"] = full_name

        if email_changed and email and new_token:
            verify_url = request.host_url.rstrip("/") + url_for("verify_email", token=new_token)
            send_email(email, "Xác minh email mới — PTIT Lost & Found",
                f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;background:#f8fafc;border-radius:12px;">
                <h2 style="color:#16a34a;">Xác minh địa chỉ email mới</h2>
                <p>Xin chào <strong>{full_name}</strong>,</p>
                <p>Email của bạn đã được cập nhật. Nhấn nút dưới để xác minh.</p>
                <a href="{verify_url}" style="display:inline-block;margin-top:12px;padding:10px 24px;background:#16a34a;color:white;border-radius:8px;text-decoration:none;font-weight:700;">Xác minh email →</a>
                </div>""")
            return jsonify({"ok": True, "msg": "Đã cập nhật! Email mới cần xác minh — kiểm tra hộp thư.", "email_changed": True})

        return jsonify({"ok": True, "msg": "Đã cập nhật thông tin thành công.", "email_changed": False})


    @app.route("/profile/change-password", methods=["POST"])
    @login_required
    def change_password():
        current  = request.form.get("current_password", "").strip()
        new_pass = request.form.get("new_password", "").strip()
        confirm  = request.form.get("confirm_password", "").strip()

        if not current:
            return jsonify({"ok": False, "msg": "Vui lòng nhập mật khẩu hiện tại."})
        if len(new_pass) < 6:
            return jsonify({"ok": False, "msg": "Mật khẩu mới phải có ít nhất 6 ký tự."})
        if new_pass != confirm:
            return jsonify({"ok": False, "msg": "Xác nhận mật khẩu không khớp."})

        conn = connect_db()
        user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not check_password_hash(user["password"], current):
            conn.close()
            return jsonify({"ok": False, "msg": "Mật khẩu hiện tại không đúng."})

        conn.execute(
            "UPDATE users SET password=? WHERE id=?",
            (generate_password_hash(new_pass), session["user_id"])
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "msg": "Đã đổi mật khẩu thành công."})


    @app.route("/profile/upload-avatar", methods=["POST"])
    @login_required
    def upload_avatar():
        if "avatar" not in request.files:
            return jsonify({"ok": False, "msg": "Không có file."})
        file = request.files["avatar"]
        if not file or file.filename == "":
            return jsonify({"ok": False, "msg": "Chưa chọn ảnh."})
        if not allowed_file(file.filename):
            return jsonify({"ok": False, "msg": "Chỉ chấp nhận PNG, JPG, JPEG, GIF."})

        # Lưu vào avatars/ riêng
        avatars_dir = os.path.join(UPLOAD_FOLDER, "avatars")
        os.makedirs(avatars_dir, exist_ok=True)

        try:
            from PIL import Image as _PILImage
            import io as _io
            img = _PILImage.open(file.stream).convert("RGB")
            img.thumbnail((300, 300), _PILImage.LANCZOS)
            fname = f"avatar_{session['user_id']}_{int(datetime.now().timestamp())}.jpg"
            img.save(os.path.join(avatars_dir, fname), "JPEG", quality=90, optimize=True)
        except Exception:
            file.stream.seek(0)
            from werkzeug.utils import secure_filename
            fname = f"avatar_{session['user_id']}_{int(datetime.now().timestamp())}.jpg"
            file.save(os.path.join(avatars_dir, fname))

        conn = connect_db()
        # Xóa avatar cũ nếu có
        old = conn.execute("SELECT avatar FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if old and old["avatar"]:
            old_path = os.path.join(avatars_dir, old["avatar"])
            try:
                if os.path.exists(old_path):
                    os.remove(old_path)
            except Exception:
                pass
        conn.execute("UPDATE users SET avatar=? WHERE id=?", (fname, session["user_id"]))
        conn.commit()
        conn.close()

        session["avatar"] = fname
        avatar_url = url_for("static", filename=f"uploads/avatars/{fname}")
        return jsonify({"ok": True, "msg": "Đã cập nhật ảnh đại diện.", "avatar_url": avatar_url})


    @app.route("/profile/resend-verify", methods=["POST"])
    @login_required
    def resend_verify_email():
        conn = connect_db()
        user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not user["email"]:
            conn.close()
            return jsonify({"ok": False, "msg": "Tài khoản chưa có email."})
        if user["email_verified"]:
            conn.close()
            return jsonify({"ok": False, "msg": "Email đã được xác minh rồi."})
        token = generate_email_token()
        conn.execute("UPDATE users SET email_token=? WHERE id=?", (token, session["user_id"]))
        conn.commit()
        conn.close()

        verify_url = request.host_url.rstrip("/") + url_for("verify_email", token=token)
        send_email(user["email"], "Xác minh email — PTIT Lost & Found",
            f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;background:#f8fafc;border-radius:12px;">
            <h2 style="color:#16a34a;">Xác minh địa chỉ email</h2>
            <p>Xin chào <strong>{user['full_name']}</strong>,</p>
            <p>Nhấn nút dưới để xác minh email <strong>{user['email']}</strong>.</p>
            <a href="{verify_url}" style="display:inline-block;margin-top:12px;padding:10px 24px;background:#16a34a;color:white;border-radius:8px;text-decoration:none;font-weight:700;">Xác minh email →</a>
            </div>""")
        return jsonify({"ok": True, "msg": "Đã gửi lại email xác minh. Kiểm tra hộp thư!"})


    @app.route("/my-posts")
    @login_required
    def my_posts():
        conn   = connect_db()
        posts  = conn.execute("SELECT * FROM posts WHERE user_id=? ORDER BY id DESC", (session["user_id"],)).fetchall()
        conn.close()
        return render_template("my_posts.html", posts=posts)


    @app.route("/resolve/<int:post_id>", methods=["POST"])
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


    @app.route("/delete/<int:post_id>", methods=["POST"])
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
