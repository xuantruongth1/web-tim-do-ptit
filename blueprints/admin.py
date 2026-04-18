"""Routes: all /admin/* routes."""
from datetime import datetime, timedelta
from flask import request, session, flash, redirect, url_for, render_template, Response
from werkzeug.security import generate_password_hash
from database import connect_db
from decorators import login_required, admin_required
from utils import log_admin_action, save_uploaded_file
from email_utils import send_email
from settings_utils import get_all_settings, get_vip_packages


def register_routes(app, _rate):

    @app.route("/admin")
    @login_required
    @admin_required
    def admin_dashboard():
        conn = connect_db()
        total_users    = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
        total_posts    = conn.execute("SELECT COUNT(*) AS total FROM posts").fetchone()["total"]
        active_posts   = conn.execute("SELECT COUNT(*) AS total FROM posts WHERE status='active'").fetchone()["total"]
        resolved_posts = conn.execute("SELECT COUNT(*) AS total FROM posts WHERE status='resolved'").fetchone()["total"]
        pending_posts  = conn.execute("SELECT COUNT(*) AS total FROM posts WHERE status='pending_review'").fetchone()["total"]

        total_claims   = conn.execute("SELECT COUNT(*) as c FROM claims").fetchone()["c"]
        pending_claims = conn.execute("SELECT COUNT(*) as c FROM claims WHERE status='pending'").fetchone()["c"]
        matched_claims = conn.execute("SELECT COUNT(*) as c FROM claims WHERE status IN ('matched','owner_confirmed')").fetchone()["c"]
        rejected_claims = conn.execute("SELECT COUNT(*) as c FROM claims WHERE status='rejected'").fetchone()["c"]
        match_rate = round(matched_claims / total_claims * 100) if total_claims else 0

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

        vip_posts        = conn.execute("SELECT COUNT(*) as c FROM posts WHERE priority > 0 AND status='active'").fetchone()["c"]
        locked_users     = conn.execute("SELECT COUNT(*) as c FROM users WHERE is_locked=1").fetchone()["c"]
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
        pkgs = get_vip_packages()
        package = pkgs.get(payment["package_key"])
        if not package:
            conn.close()
            flash("Gói thanh toán không hợp lệ.", "danger")
            return redirect(url_for("admin_payments"))
        now = datetime.now()
        conn.execute("UPDATE payments SET status='paid', confirmed_at=? WHERE id=?",
                     (str(now), payment_id))
        post = conn.execute("SELECT * FROM posts WHERE id=?", (payment["post_id"],)).fetchone()
        if post and post["status"] == "active":
            days = package["days"]
            conn.execute("""
                UPDATE posts SET priority=?, package_key=?, vip_started_at=?, vip_expires_at=? WHERE id=?
            """, (package["priority"], payment["package_key"], str(now),
                  str(now + timedelta(days=days)), payment["post_id"]))
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
        contact_unlocked_val = 1 if status == "matched" else 0
        update_fields = "status=?, contact_unlocked=?"
        params = [status, contact_unlocked_val]
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
        new_priority = post["priority"]
        pkg_key = post["package_key"] if post["package_key"] else None
        pkgs = get_vip_packages()
        if pkg_key and pkg_key in pkgs:
            pkg = pkgs[pkg_key]
            # Auto-confirm pending payment khi duyệt bài
            pending_pay = conn.execute(
                "SELECT id FROM payments WHERE post_id=? AND status='pending' LIMIT 1", (post_id,)
            ).fetchone()
            if pending_pay:
                conn.execute("UPDATE payments SET status='paid', confirmed_at=? WHERE id=?",
                             (str(now), pending_pay["id"]))
            # Tính VIP nếu đã có (hoặc vừa xác nhận) thanh toán
            has_paid = pending_pay or conn.execute(
                "SELECT id FROM payments WHERE post_id=? AND status='paid' LIMIT 1", (post_id,)
            ).fetchone()
            if has_paid:
                vip_started_at = str(now)
                vip_expires_at = str(now + timedelta(days=pkg["days"]))
                new_priority = pkg["priority"]
        conn.execute("""
            UPDATE posts SET status='active', priority=?, vip_started_at=?, vip_expires_at=? WHERE id=?
        """, (new_priority, vip_started_at, vip_expires_at, post_id))
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
        if post and owner and owner["email"]:
            send_email(owner["email"], f"Bài đăng #{post_id} bị từ chối",
                f"<p>Xin chào <strong>{owner['full_name']}</strong>,</p>"
                f"<p>Bài đăng <strong>#{post_id}: {post['title']}</strong> đã bị admin từ chối.</p>"
                f"<p>Vui lòng kiểm tra lại nội dung và đăng lại nếu cần.</p>")
        flash(f"Đã từ chối bài đăng #{post_id}.", "warning")
        return redirect(url_for("admin_posts"))


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
                               vip_packages=get_vip_packages(),
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
        pkgs = get_vip_packages()
        priority = post["priority"] if post["priority"] > 0 else pkgs.get(pkg_key, {}).get("priority", 1)
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
        pkgs = get_vip_packages()
        if new_pkg == "free":
            conn.execute("""
                UPDATE posts SET package_key=NULL, priority=0,
                    vip_started_at=NULL, vip_expires_at=NULL WHERE id=?
            """, (post_id,))
            log_admin_action(conn, f"Gỡ VIP bài #{post_id}", "post", post_id)
            flash(f"Đã gỡ VIP bài #{post_id} → Tin thường.", "success")
        elif new_pkg in pkgs:
            pkg = pkgs[new_pkg]
            now = datetime.now()
            conn.execute("""
                UPDATE posts SET package_key=?, priority=?, vip_started_at=?, vip_expires_at=? WHERE id=?
            """, (new_pkg, pkg["priority"], str(now), str(now + timedelta(days=pkg["days"])), post_id))
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
            flash("Định dạng ngày không hợp lệ.", "danger")
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


    @app.route("/admin/revenue")
    @login_required
    @admin_required
    def admin_revenue():
        period  = request.args.get("period", "month")
        from_dt = request.args.get("from", "")
        to_dt   = request.args.get("to", "")
        conn = connect_db()
        date_cond, date_params = "", []
        if from_dt:
            date_cond += " AND date(created_at) >= ?"
            date_params.append(from_dt)
        if to_dt:
            date_cond += " AND date(created_at) <= ?"
            date_params.append(to_dt)
        total_revenue = conn.execute(
            f"SELECT COALESCE(SUM(amount),0) as t FROM payments WHERE status='paid'{date_cond}",
            date_params
        ).fetchone()["t"]
        total_count   = conn.execute(
            f"SELECT COUNT(*) as c FROM payments WHERE status='paid'{date_cond}", date_params
        ).fetchone()["c"]
        pending_count = conn.execute("SELECT COUNT(*) as c FROM payments WHERE status='pending'").fetchone()["c"]
        by_package = conn.execute(f"""
            SELECT package_key, package_name, COUNT(*) as cnt,
                   COALESCE(SUM(amount),0) as total
            FROM payments WHERE status='paid'{date_cond}
            GROUP BY package_key ORDER BY total DESC
        """, date_params).fetchall()
        if period == "day":
            grp, lbl = "date(created_at)", "Ngày"
        elif period == "week":
            grp, lbl = "strftime('%Y-W%W', created_at)", "Tuần"
        else:
            grp, lbl = "strftime('%Y-%m', created_at)", "Tháng"
        by_period = conn.execute(f"""
            SELECT {grp} as period_key, COUNT(*) as cnt,
                   COALESCE(SUM(amount),0) as total
            FROM payments WHERE status='paid'{date_cond}
            GROUP BY {grp} ORDER BY period_key DESC LIMIT 24
        """, date_params).fetchall()
        by_period_asc = list(reversed(list(by_period)))
        conn.close()
        return render_template("admin_revenue.html",
            total_revenue=total_revenue, total_count=total_count,
            pending_count=pending_count,
            by_package=by_package, by_period=by_period, by_period_asc=by_period_asc,
            period=period, period_lbl=lbl,
            from_dt=from_dt, to_dt=to_dt,
            vip_packages=get_vip_packages())


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
        posts = conn.execute("SELECT * FROM posts WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()
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
            now = datetime.now()
            pkgs = get_vip_packages()
            for pid in valid_ids:
                post = conn.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
                if post and post["status"] == "pending_review":
                    vip_started_at = vip_expires_at = None
                    new_priority = post["priority"]
                    pkg_key = post["package_key"]
                    if pkg_key and pkg_key in pkgs:
                        pkg = pkgs[pkg_key]
                        pending_pay = conn.execute(
                            "SELECT id FROM payments WHERE post_id=? AND status='pending' LIMIT 1", (pid,)
                        ).fetchone()
                        if pending_pay:
                            conn.execute("UPDATE payments SET status='paid', confirmed_at=? WHERE id=?",
                                         (str(now), pending_pay["id"]))
                        has_paid = pending_pay or conn.execute(
                            "SELECT id FROM payments WHERE post_id=? AND status='paid' LIMIT 1", (pid,)
                        ).fetchone()
                        if has_paid:
                            vip_started_at = str(now)
                            vip_expires_at = str(now + timedelta(days=pkg["days"]))
                            new_priority = pkg["priority"]
                    conn.execute(
                        "UPDATE posts SET status='active', priority=?, vip_started_at=?, vip_expires_at=? WHERE id=?",
                        (new_priority, vip_started_at, vip_expires_at, pid)
                    )
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


    @app.route("/admin/vip/grant", methods=["POST"])
    @login_required
    @admin_required
    def admin_vip_grant():
        post_id = request.form.get("post_id", "").strip()
        pkg_key = request.form.get("package_key", "").strip()
        reason  = request.form.get("reason", "Admin tặng").strip()
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
        vip_end = str(now + timedelta(days=pkg["days"]))
        conn.execute("""
            UPDATE posts SET package_key=?, priority=?, vip_started_at=?, vip_expires_at=? WHERE id=?
        """, (pkg_key, pkg["priority"], str(now), vip_end, post_id))
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


    @app.route("/admin/reports")
    @login_required
    @admin_required
    def admin_reports():
        status_filter = request.args.get("status", "pending")
        page = max(1, request.args.get("page", 1, type=int))
        per_page = 20
        conn = connect_db()
        total = conn.execute(
            "SELECT COUNT(*) as c FROM reports WHERE status=?", (status_filter,)
        ).fetchone()["c"]
        total_pages = max(1, (total + per_page - 1) // per_page)
        reports = conn.execute("""
            SELECT r.*, u.full_name as reporter_name, u.username as reporter_username,
                   p.title as post_title
            FROM reports r
            LEFT JOIN users u ON r.reporter_user_id = u.id
            LEFT JOIN posts p ON r.post_id = p.id
            WHERE r.status = ?
            ORDER BY r.id DESC LIMIT ? OFFSET ?
        """, (status_filter, per_page, (page - 1) * per_page)).fetchall()
        conn.close()
        return render_template("admin_reports.html",
                               reports=reports, status_filter=status_filter,
                               page=page, total_pages=total_pages, total=total)


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
            conn.execute("UPDATE posts SET is_scam_warned=1 WHERE id=?", (report["post_id"],))
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


    @app.route("/admin/vouchers")
    @login_required
    @admin_required
    def admin_vouchers():
        conn = connect_db()
        vouchers = conn.execute("SELECT * FROM vouchers ORDER BY id DESC").fetchall()
        conn.close()
        return render_template("admin_vouchers.html", vouchers=vouchers, vip_packages=get_vip_packages())


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
        log_admin_action(conn, f"Hoàn tiền payment #{payment_id}", "payment", payment_id, f"Lý do: {note}")
        conn.commit()
        conn.close()
        flash(f"Đã đánh dấu hoàn tiền cho giao dịch #{payment_id}.", "success")
        return redirect(url_for("admin_payments"))


    @app.route("/admin/export/revenue.csv")
    @login_required
    @admin_required
    def admin_export_revenue_csv():
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


    @app.route("/admin/api/stats")
    @login_required
    @admin_required
    def admin_api_stats():
        from flask import jsonify
        period = request.args.get("period", "7days")
        conn = connect_db()
        days = 30 if period == "30days" else 7
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
            if target == "no_post":
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
