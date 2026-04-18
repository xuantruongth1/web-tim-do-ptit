"""Routes: create_post, edit_post, post_success, lost_posts, found_posts, premium_posts,
post_detail, add_comment, delete_comment, edit_comment, submit_report."""
import os
import shutil
from datetime import datetime
from flask import request, session, flash, redirect, url_for, render_template
from database import connect_db
from decorators import login_required
from utils import save_uploaded_file, check_banned_words, log_admin_action, downgrade_expired_priorities
from email_utils import send_email
from settings_utils import get_vip_packages
from config import BASE_DIR, PER_PAGE


def register_routes(app, _rate):

    @app.route("/create", methods=["GET", "POST"])
    @login_required
    def create_post():
        # Kiểm tra xác minh email trước khi cho phép đăng bài
        conn_chk = connect_db()
        user_chk = conn_chk.execute(
            "SELECT email, email_verified FROM users WHERE id=?", (session["user_id"],)
        ).fetchone()
        conn_chk.close()
        if session.get("role") not in ("admin", "moderator") and (not user_chk["email"] or not user_chk["email_verified"]):
            return redirect(url_for("profile", verify_popup="1"))

        packages = get_vip_packages()
        if request.method == "POST":
            title      = request.form.get("title", "").strip()
            category   = request.form.get("category", "").strip()
            description = request.form.get("description", "").strip()
            event_date = request.form.get("event_date", "").strip()
            location   = request.form.get("location", "").strip()
            city       = request.form.get("city", "").strip()
            campus     = request.form.get("campus", "").strip()
            contact    = request.form.get("contact", "").strip()
            post_type  = request.form.get("post_type", "lost").strip()
            verification_hint         = request.form.get("verification_hint", "").strip()
            private_verification_note = request.form.get("private_verification_note", "").strip()
            raw_tags = request.form.get("tags", "").strip()
            tags = ",".join(t.strip().lower()[:30] for t in raw_tags.split(",") if t.strip())[:93]
            selected_package = request.form.get("selected_package", "free").strip()

            form_data = {
                "post_type": post_type, "title": title, "description": description,
                "category": category, "event_date": event_date, "location": location,
                "city": city, "campus": campus, "contact": contact,
                "verification_hint": verification_hint,
                "private_verification_note": private_verification_note,
                "tags": raw_tags, "selected_package": selected_package,
                "sample_image_key": request.form.get("sample_image_key", ""),
            }

            def _err(msg, category="danger"):
                flash(msg, category)
                cats = connect_db().execute("SELECT * FROM categories ORDER BY sort_order").fetchall()
                return render_template("create_post.html", packages=packages,
                                       categories=cats, form_data=form_data)

            conn_bw = connect_db()
            banned = check_banned_words(conn_bw, title, description)
            conn_bw.close()
            if banned:
                return _err(f"Nội dung chứa từ không được phép: «{banned}».")
            if not verification_hint:
                return _err("Vui lòng nhập Thông tin xác thực — đây là trường bắt buộc.")
            if not private_verification_note:
                return _err("Vui lòng nhập Ghi chú riêng tư — đây là trường bắt buộc.")
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
                        shutil.copy2(src, os.path.join(BASE_DIR, "static", "uploads", dest_name))
                        image_name = dest_name

            priority = 0
            package_key = None
            if selected_package in packages and post_type == "lost":
                priority = packages[selected_package]["priority"]
                package_key = selected_package

            conn = connect_db()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO posts (title, category, description, event_date, location, city, campus, contact, "
                "image, post_type, status, priority, created_at, user_id, verification_hint, "
                "private_verification_note, package_key, tags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (title, category, description, event_date, location, city, campus, contact,
                 image_name, post_type, "pending_review", priority, str(datetime.now()),
                 session["user_id"], verification_hint, private_verification_note, package_key, tags)
            )
            post_id = cursor.lastrowid
            if package_key:
                pkg = packages[package_key]
                transfer_content = f"LF-{post_id}-{package_key}-{session.get('username','')}"
                proof_name = save_uploaded_file(request.files.get("payment_proof"))
                conn.execute(
                    "INSERT INTO payments (user_id, post_id, package_key, package_name, amount, "
                    "transfer_content, status, created_at, payment_proof) VALUES (?,?,?,?,?,?,?,?,?)",
                    (session["user_id"], post_id, package_key, pkg["name"],
                     pkg["price"], transfer_content, "pending", str(datetime.now()), proof_name)
                )
            conn.commit()
            conn.close()
            admin_email = os.environ.get("MAIL_USERNAME", "")
            if admin_email:
                send_email(admin_email, f"Bài đăng mới chờ duyệt #{post_id}",
                    f"<p>Bài #{post_id}: <strong>{title}</strong> — @{session.get('username','')}</p>"
                    f"<a href='{request.host_url}admin/posts?status=pending_review'>Duyệt ngay →</a>")
            return redirect(url_for("post_success", post_id=post_id))
        categories = connect_db().execute("SELECT * FROM categories ORDER BY sort_order").fetchall()
        return render_template("create_post.html", packages=packages, categories=categories, form_data={})


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
            title      = request.form["title"].strip()
            category   = request.form["category"].strip()
            description = request.form.get("description", "").strip()
            event_date = request.form.get("event_date", "").strip()
            location   = request.form["location"].strip()
            city       = request.form.get("city", "").strip()
            campus     = request.form.get("campus", "").strip()
            contact    = request.form["contact"].strip()
            verification_hint         = request.form.get("verification_hint", "").strip()
            private_verification_note = request.form.get("private_verification_note", "").strip()
            raw_tags = request.form.get("tags", "").strip()
            tags = ",".join(t.strip().lower()[:30] for t in raw_tags.split(",") if t.strip())[:93]
            image_name = post["image"]
            if "image" in request.files:
                new_img = save_uploaded_file(request.files["image"])
                if new_img:
                    image_name = new_img
            conn.execute(
                "UPDATE posts SET title=?, category=?, description=?, event_date=?, location=?, "
                "city=?, campus=?, contact=?, image=?, verification_hint=?, private_verification_note=?, tags=? WHERE id=?",
                (title, category, description, event_date, location, city, campus,
                 contact, image_name, verification_hint, private_verification_note, tags, post_id)
            )
            conn.commit()
            conn.close()
            flash("Đã cập nhật bài đăng.", "success")
            return redirect(url_for("post_detail", post_id=post_id))
        categories = conn.execute("SELECT * FROM categories ORDER BY sort_order").fetchall()
        conn.close()
        return render_template("edit_post.html", post=post, categories=categories)


    @app.route("/post-success/<int:post_id>")
    @login_required
    def post_success(post_id):
        conn = connect_db()
        post = conn.execute(
            "SELECT p.*, u.full_name FROM posts p LEFT JOIN users u ON p.user_id=u.id WHERE p.id=?",
            (post_id,)
        ).fetchone()
        conn.close()
        if not post or post["user_id"] != session["user_id"]:
            return redirect(url_for("home"))
        return render_template("post_success.html", post=post)


    @app.route("/lost")
    def lost_posts():
        downgrade_expired_priorities()
        page  = request.args.get("page", 1, type=int)
        conn  = connect_db()
        total = conn.execute("SELECT COUNT(*) as c FROM posts WHERE post_type='lost' AND status='active'").fetchone()["c"]
        posts = conn.execute(
            "SELECT p.*, u.full_name FROM posts p LEFT JOIN users u ON p.user_id=u.id "
            "WHERE p.post_type='lost' AND p.status='active' ORDER BY p.priority DESC, p.id DESC LIMIT ? OFFSET ?",
            (PER_PAGE, (page - 1) * PER_PAGE)
        ).fetchall()
        conn.close()
        return render_template("posts.html", page_title="Tin mất & thất lạc", posts=posts,
            current_type="lost", page=page, total_pages=max(1, (total + PER_PAGE - 1) // PER_PAGE), total=total)


    @app.route("/found")
    def found_posts():
        downgrade_expired_priorities()
        page  = request.args.get("page", 1, type=int)
        conn  = connect_db()
        total = conn.execute("SELECT COUNT(*) as c FROM posts WHERE post_type='found' AND status='active'").fetchone()["c"]
        posts = conn.execute(
            "SELECT p.*, u.full_name FROM posts p LEFT JOIN users u ON p.user_id=u.id "
            "WHERE p.post_type='found' AND p.status='active' ORDER BY p.priority DESC, p.id DESC LIMIT ? OFFSET ?",
            (PER_PAGE, (page - 1) * PER_PAGE)
        ).fetchall()
        conn.close()
        return render_template("posts.html", page_title="Nhặt được & tìm thấy", posts=posts,
            current_type="found", page=page, total_pages=max(1, (total + PER_PAGE - 1) // PER_PAGE), total=total)


    @app.route("/premium")
    def premium_posts():
        downgrade_expired_priorities()
        page  = request.args.get("page", 1, type=int)
        conn  = connect_db()
        total = conn.execute("SELECT COUNT(*) as c FROM posts WHERE status='active' AND priority>0").fetchone()["c"]
        posts = conn.execute(
            "SELECT p.*, u.full_name FROM posts p LEFT JOIN users u ON p.user_id=u.id "
            "WHERE p.status='active' AND p.priority>0 ORDER BY p.priority DESC, p.id DESC LIMIT ? OFFSET ?",
            (PER_PAGE, (page - 1) * PER_PAGE)
        ).fetchall()
        conn.close()
        return render_template("posts.html", page_title="Bài đăng trả phí", posts=posts,
            current_type="premium", page=page, total_pages=max(1, (total + PER_PAGE - 1) // PER_PAGE), total=total)


    @app.route("/post/<int:post_id>")
    def post_detail(post_id):
        conn = connect_db()
        post = conn.execute(
            "SELECT p.*, u.full_name FROM posts p LEFT JOIN users u ON p.user_id=u.id WHERE p.id=?",
            (post_id,)
        ).fetchone()
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
                    unlocked = conn.execute(
                        "SELECT id FROM claims WHERE found_post_id=? AND claimer_user_id=? AND contact_unlocked=1 LIMIT 1",
                        (post_id, user_id)
                    ).fetchone()
                    contact_unlocked = unlocked is not None
                    my_lost_posts = conn.execute(
                        "SELECT * FROM posts WHERE user_id=? AND post_type='lost' ORDER BY id DESC",
                        (user_id,)
                    ).fetchall()
        related_posts = conn.execute(
            "SELECT p.*, u.full_name FROM posts p LEFT JOIN users u ON p.user_id=u.id "
            "WHERE p.category=? AND p.id!=? AND p.status='active' AND p.post_type!=? "
            "ORDER BY p.priority DESC, p.id DESC LIMIT 4",
            (post["category"], post_id, post["post_type"])
        ).fetchall()
        if len(related_posts) < 4 and post["city"]:
            exclude_ids = [r["id"] for r in related_posts] or [0]
            placeholders = ",".join("?" * len(exclude_ids))
            extra = conn.execute(
                f"SELECT p.*, u.full_name FROM posts p LEFT JOIN users u ON p.user_id=u.id "
                f"WHERE p.city=? AND p.id!=? AND p.status='active' AND p.id NOT IN ({placeholders}) "
                f"ORDER BY p.priority DESC, p.id DESC LIMIT ?",
                [post["city"], post_id] + exclude_ids + [4 - len(related_posts)]
            ).fetchall()
            related_posts = list(related_posts) + list(extra)
        comments = conn.execute(
            "SELECT c.*, u.full_name, u.username, u.role, u.avatar FROM comments c "
            "JOIN users u ON c.user_id=u.id WHERE c.post_id=? ORDER BY c.id ASC",
            (post_id,)
        ).fetchall()
        confirmed_claim_id = None
        if session.get("user_id") and post["post_type"] == "found":
            confirmed = conn.execute(
                "SELECT id FROM claims WHERE found_post_id=? AND claimer_user_id=? AND status='owner_confirmed' LIMIT 1",
                (post_id, session["user_id"])
            ).fetchone()
            if confirmed:
                confirmed_claim_id = confirmed["id"]
        approved_reports = conn.execute(
            "SELECT r.*, u.full_name as reporter_name FROM reports r "
            "LEFT JOIN users u ON r.reporter_user_id=u.id WHERE r.post_id=? AND r.status='approved' ORDER BY r.id DESC",
            (post_id,)
        ).fetchall()
        user_already_reported = False
        if session.get("user_id"):
            user_already_reported = conn.execute(
                "SELECT id FROM reports WHERE post_id=? AND reporter_user_id=? AND status!='rejected'",
                (post_id, session["user_id"])
            ).fetchone() is not None
        conn.close()
        return render_template("post_detail.html", post=post,
            contact_unlocked=contact_unlocked, my_lost_posts=my_lost_posts,
            related_posts=related_posts, comments=comments,
            confirmed_claim_id=confirmed_claim_id,
            approved_reports=approved_reports,
            user_already_reported=user_already_reported)


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
        post = conn.execute(
            "SELECT p.*, u.email, u.full_name FROM posts p JOIN users u ON p.user_id=u.id WHERE p.id=?",
            (post_id,)
        ).fetchone()
        conn.execute(
            "INSERT INTO comments (post_id, user_id, content, created_at) VALUES (?,?,?,?)",
            (post_id, session["user_id"], content, str(datetime.now()))
        )
        conn.commit()
        conn.close()
        if post and post["user_id"] != session["user_id"]:
            conn2 = connect_db()
            conn2.execute(
                "INSERT INTO notifications (user_id, type, message, link, created_at) VALUES (?,?,?,?,?)",
                (post["user_id"], "comment",
                 f"{session.get('full_name','Ai đó')} đã bình luận bài \"{post['title'][:40]}\"",
                 f"/post/{post_id}#comments",
                 str(datetime.now()))
            )
            conn2.commit()
            conn2.close()
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
            log_admin_action(conn, f"Xóa bình luận #{comment_id}", "comment", comment_id)
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
        conn.commit()
        conn.close()
        flash("Đã cập nhật bình luận.", "success")
        return redirect(url_for("post_detail", post_id=post_id) + "#comments")


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
            "SELECT id FROM reports WHERE post_id=? AND reporter_user_id=? AND status!='rejected'",
            (post_id, session["user_id"])
        ).fetchone()
        if existing:
            conn.close()
            flash("Bạn đã báo cáo bài đăng này rồi.", "warning")
            return redirect(url_for("post_detail", post_id=post_id))
        content = request.form.get("content", "").strip()
        if not content or len(content) > 2000:
            conn.close()
            flash("Vui lòng nhập nội dung báo cáo (tối đa 2000 ký tự).", "warning")
            return redirect(url_for("post_detail", post_id=post_id))
        conn.execute(
            "INSERT INTO reports (post_id, reporter_user_id, content, status, created_at) VALUES (?,?,?,'pending',?)",
            (post_id, session["user_id"], content, str(datetime.now()))
        )
        conn.commit()
        conn.close()
        flash("Báo cáo của bạn đã được gửi. Admin sẽ xem xét sớm nhất có thể.", "success")
        return redirect(url_for("post_detail", post_id=post_id))
