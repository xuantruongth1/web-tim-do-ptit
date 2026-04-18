"""Routes: claim_form, my_claims, my_received_claims, confirm_claim_owner, reject_claim_owner."""
from datetime import datetime, timedelta
from flask import request, session, flash, redirect, url_for, render_template
from database import connect_db
from decorators import login_required
from utils import match_score
from ai_utils import claude_analyze_claim
from email_utils import send_email


def register_routes(app, _rate):

    @app.route("/claim/<int:found_post_id>", methods=["GET", "POST"])
    @login_required
    def claim_form(found_post_id):
        if request.method == "GET":
            flash("Để xác minh, vui lòng dùng nút \"Đây là đồ của tôi\" trực tiếp trên trang chi tiết bài.", "info")
            return redirect(url_for("post_detail", post_id=found_post_id))

        conn = connect_db()
        found_post = conn.execute(
            "SELECT * FROM posts WHERE id=? AND post_type='found'", (found_post_id,)
        ).fetchone()

        if not found_post:
            conn.close()
            flash("Không tìm thấy bài đăng nhặt đồ.", "danger")
            return redirect(url_for("home"))

        if found_post["user_id"] == session["user_id"]:
            conn.close()
            flash("Bạn không thể xác minh đồ do chính mình đăng.", "warning")
            return redirect(url_for("post_detail", post_id=found_post_id))

        claim_description = request.form.get("claim_description", "").strip()
        if not claim_description:
            conn.close()
            flash("Vui lòng nhập nội dung xác minh.", "danger")
            return redirect(url_for("post_detail", post_id=found_post_id))

        existing = conn.execute("""
            SELECT created_at FROM claims
            WHERE found_post_id=? AND claimer_user_id=?
            ORDER BY id DESC LIMIT 1
        """, (found_post_id, session["user_id"])).fetchone()

        if existing:
            try:
                claim_dt = datetime.fromisoformat(existing["created_at"][:19])
                wait = timedelta(hours=1) - (datetime.now() - claim_dt)
                if wait.total_seconds() > 0:
                    conn.close()
                    mins = max(1, int(wait.total_seconds() / 60))
                    flash(f"Bạn đã gửi xác minh cho bài này rồi. Vui lòng đợi thêm {mins} phút.", "warning")
                    return redirect(url_for("post_detail", post_id=found_post_id))
            except Exception:
                pass

        lost_post_id_raw = request.form.get("lost_post_id") or None
        lost_post_id = int(lost_post_id_raw) if lost_post_id_raw else None
        lost_post = conn.execute("SELECT * FROM posts WHERE id=?", (lost_post_id,)).fetchone() if lost_post_id else None

        ai_score, ai_reason = claude_analyze_claim(found_post, claim_description, lost_post)

        if ai_score is not None:
            final_score = ai_score
        else:
            base_score = match_score(lost_post, found_post) if lost_post else 0
            words = claim_description.lower().split()
            found_desc   = (found_post["description"] or "").lower()
            found_hint   = (found_post.get("verification_hint") or "").lower()
            private_hint = (found_post.get("private_verification_note") or "").lower()
            match_word_count = sum(
                1 for w in words if len(w) > 3 and (w in found_desc or w in found_hint or w in private_hint)
            )
            final_score = min(100, base_score + match_word_count * 5)
            ai_reason = None

        status = "matched" if final_score >= 50 else "low_match"
        contact_unlocked_val = 1 if final_score >= 50 else 0

        conn.execute("""
            INSERT INTO claims (lost_post_id, found_post_id, claimer_user_id,
                claim_description, ai_score, status, created_at, contact_unlocked, ai_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (lost_post_id, found_post_id, session["user_id"],
              claim_description, final_score, status, str(datetime.now()),
              contact_unlocked_val, ai_reason))
        conn.commit()

        if final_score >= 50:
            found_owner = conn.execute(
                "SELECT email, full_name FROM users WHERE id=?", (found_post["user_id"],)
            ).fetchone()
            if found_owner and found_owner["email"]:
                send_email(found_owner["email"], "Có người khớp với đồ bạn đăng!",
                    f"<p>Xin chào <strong>{found_owner['full_name']}</strong>,</p>"
                    f"<p>Có người vừa xác minh với điểm <strong>{final_score}/100</strong> cho bài nhặt được của bạn: "
                    f"<em>{found_post['title']}</em>.</p>"
                    f"<p><a href='{request.host_url}my-received-claims'>Xem yêu cầu nhận đồ →</a></p>")
        conn.close()

        source = "AI" if ai_score is not None else "thuật toán"
        if final_score >= 50:
            flash(f"Điểm xác minh ({source}): {final_score}/100 — Thông tin liên hệ đã được mở khóa!", "success")
        else:
            flash(f"Điểm xác minh ({source}): {final_score}/100 — Chưa đủ điểm. Người nhặt được sẽ xem xét.", "warning")
        return redirect(url_for("post_detail", post_id=found_post_id))


    @app.route("/my-claims")
    @login_required
    def my_claims():
        conn = connect_db()
        claims = conn.execute("""
            SELECT c.*, p.title as found_title
            FROM claims c LEFT JOIN posts p ON c.found_post_id = p.id
            WHERE c.claimer_user_id=? ORDER BY c.id DESC
        """, (session["user_id"],)).fetchall()
        conn.close()
        return render_template("my_claims.html", claims=claims)


    @app.route("/my-received-claims")
    @login_required
    def my_received_claims():
        conn = connect_db()
        claims = conn.execute("""
            SELECT c.*, p_found.title as found_title, p_found.id as found_id,
                   p_lost.title as lost_title,
                   u.full_name as claimer_name, u.username as claimer_username
            FROM claims c
            LEFT JOIN posts p_found ON c.found_post_id = p_found.id
            LEFT JOIN posts p_lost  ON c.lost_post_id  = p_lost.id
            LEFT JOIN users u       ON c.claimer_user_id = u.id
            WHERE p_found.user_id=? ORDER BY c.id DESC
        """, (session["user_id"],)).fetchall()
        conn.close()
        return render_template("my_received_claims.html", claims=claims)


    @app.route("/claim/confirm/<int:claim_id>", methods=["POST"])
    @login_required
    def confirm_claim_owner(claim_id):
        conn = connect_db()
        claim = conn.execute("""
            SELECT c.*, p.user_id as owner_id FROM claims c
            LEFT JOIN posts p ON c.found_post_id = p.id WHERE c.id=?
        """, (claim_id,)).fetchone()

        if not claim or claim["owner_id"] != session["user_id"]:
            conn.close()
            flash("Bạn không có quyền thực hiện thao tác này.", "danger")
            return redirect(url_for("my_received_claims"))

        conn.execute("""
            UPDATE claims SET status='owner_confirmed', owner_confirmed=1,
                contact_unlocked=1, owner_reviewed_at=? WHERE id=?
        """, (str(datetime.now()), claim_id))
        conn.commit()
        conn.close()
        flash("Đã xác nhận đúng chủ. Người mất đồ có thể xem thông tin liên hệ.", "success")
        return redirect(url_for("my_received_claims"))


    @app.route("/claim/reject-owner/<int:claim_id>", methods=["POST"])
    @login_required
    def reject_claim_owner(claim_id):
        conn = connect_db()
        claim = conn.execute("""
            SELECT c.*, p.user_id as owner_id FROM claims c
            LEFT JOIN posts p ON c.found_post_id = p.id WHERE c.id=?
        """, (claim_id,)).fetchone()

        if not claim or claim["owner_id"] != session["user_id"]:
            conn.close()
            flash("Bạn không có quyền thực hiện thao tác này.", "danger")
            return redirect(url_for("my_received_claims"))

        conn.execute("UPDATE claims SET status='rejected', owner_reviewed_at=? WHERE id=?",
                     (str(datetime.now()), claim_id))
        conn.commit()
        conn.close()
        flash("Đã từ chối yêu cầu nhận đồ.", "info")
        return redirect(url_for("my_received_claims"))
