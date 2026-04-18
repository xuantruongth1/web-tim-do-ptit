"""Routes: payment."""
from datetime import datetime
from flask import request, session, flash, redirect, url_for, render_template
from database import connect_db
from decorators import login_required
from settings_utils import get_setting, get_vip_packages


def register_routes(app, _rate):

    @app.route("/payment/<package_key>", methods=["GET", "POST"])
    @login_required
    def payment(package_key):
        packages = get_vip_packages()
        package = packages.get(package_key)
        if not package:
            flash("Gói dịch vụ không hợp lệ.", "danger")
            return redirect(url_for("pricing"))

        if request.method == "POST":
            post_id_raw = request.form.get("post_id")
            if not post_id_raw:
                flash("Bạn cần chọn bài đăng để nâng cấp.", "warning")
                return redirect(url_for("my_posts"))
            post_id = int(post_id_raw)

            conn = connect_db()
            post = conn.execute(
                "SELECT * FROM posts WHERE id=? AND user_id=?",
                (post_id, session["user_id"])
            ).fetchone()

            if not post:
                conn.close()
                flash("Không tìm thấy bài đăng hợp lệ.", "danger")
                return redirect(url_for("my_posts"))

            transfer_content = f"LF-{post_id}-{package_key}-{session['username']}"
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
            transfer_username=session["username"],
            my_posts=my_posts,
        )
