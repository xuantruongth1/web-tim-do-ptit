"""Routes: my_chats, chat_view, chat_send, chat_stream, chat_poll."""
import json
from datetime import datetime
from flask import request, session, flash, redirect, url_for, render_template
from flask import Response, stream_with_context, jsonify
from database import connect_db
from decorators import login_required


def register_routes(app, _rate):

    @app.route("/my-chats")
    @login_required
    def my_chats():
        user_id = session["user_id"]
        conn = connect_db()
        chats = conn.execute("""
            SELECT c.id as claim_id, c.status,
                   fp.title as found_title, fp.id as found_post_id,
                   cu.full_name as claimer_name, cu.id as claimer_id,
                   ou.full_name as owner_name, ou.id as owner_id,
                   (SELECT COUNT(*) FROM chat_messages m
                    WHERE m.claim_id = c.id AND m.is_read = 0 AND m.sender_id != ?) as unread,
                   (SELECT m2.message FROM chat_messages m2
                    WHERE m2.claim_id = c.id ORDER BY m2.id DESC LIMIT 1) as last_message,
                   (SELECT m3.created_at FROM chat_messages m3
                    WHERE m3.claim_id = c.id ORDER BY m3.id DESC LIMIT 1) as last_at
            FROM claims c
            JOIN posts fp ON c.found_post_id = fp.id
            JOIN users cu ON c.claimer_user_id = cu.id
            JOIN users ou ON fp.user_id = ou.id
            WHERE c.status = 'owner_confirmed'
              AND (c.claimer_user_id = ? OR fp.user_id = ?)
            ORDER BY c.id DESC
        """, (user_id, user_id, user_id)).fetchall()
        conn.close()
        return render_template("my_chats.html", chats=chats)


    @app.route("/chat/<int:claim_id>")
    @login_required
    def chat_view(claim_id):
        conn = connect_db()
        claim = conn.execute("""
            SELECT c.*, fp.title as found_title, fp.user_id as found_owner_id,
                   fp.id as found_post_id_val,
                   cu.full_name as claimer_name, cu.id as claimer_id, cu.avatar as claimer_avatar,
                   ou.full_name as owner_name, ou.avatar as owner_avatar
            FROM claims c
            LEFT JOIN posts fp ON c.found_post_id = fp.id
            LEFT JOIN users cu ON c.claimer_user_id = cu.id
            LEFT JOIN users ou ON fp.user_id = ou.id
            WHERE c.id=?
        """, (claim_id,)).fetchone()
        if not claim:
            conn.close()
            flash("Không tìm thấy cuộc trò chuyện.", "danger")
            return redirect(url_for("home"))
        user_id = session["user_id"]
        if user_id not in (claim["claimer_id"], claim["found_owner_id"]) and session.get("role") != "admin":
            conn.close()
            flash("Bạn không có quyền truy cập.", "danger")
            return redirect(url_for("home"))
        if claim["status"] != "owner_confirmed":
            conn.close()
            flash("Chat chỉ khả dụng sau khi chủ đã xác nhận.", "warning")
            return redirect(url_for("post_detail", post_id=claim["found_post_id"]))
        conn.execute("UPDATE chat_messages SET is_read=1 WHERE claim_id=? AND sender_id!=?", (claim_id, user_id))
        messages = conn.execute("""
            SELECT m.*, u.full_name, u.username, u.avatar
            FROM chat_messages m JOIN users u ON m.sender_id = u.id
            WHERE m.claim_id=? ORDER BY m.id ASC
        """, (claim_id,)).fetchall()
        conn.commit()
        conn.close()
        other_name = claim["claimer_name"] if user_id == claim["found_owner_id"] else claim["owner_name"]
        other_avatar = claim["claimer_avatar"] if user_id == claim["found_owner_id"] else claim["owner_avatar"]
        return render_template("chat.html", claim=claim, messages=messages, other_name=other_name, other_avatar=other_avatar)


    @app.route("/chat/<int:claim_id>/send", methods=["POST"])
    @login_required
    def chat_send(claim_id):
        message = request.form.get("message", "").strip()
        if not message or len(message) > 1000:
            return redirect(url_for("chat_view", claim_id=claim_id))
        conn = connect_db()
        claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not claim:
            conn.close()
            return redirect(url_for("home"))
        found_owner_id = conn.execute("SELECT user_id FROM posts WHERE id=?", (claim["found_post_id"],)).fetchone()["user_id"]
        user_id = session["user_id"]
        if user_id not in (claim["claimer_user_id"], found_owner_id) and session.get("role") != "admin":
            conn.close()
            return redirect(url_for("home"))
        if claim["status"] != "owner_confirmed":
            conn.close()
            return redirect(url_for("post_detail", post_id=claim["found_post_id"]))
        conn.execute(
            "INSERT INTO chat_messages (claim_id, sender_id, message, created_at) VALUES (?,?,?,?)",
            (claim_id, user_id, message, str(datetime.now()))
        )
        conn.commit()
        conn.close()
        return redirect(url_for("chat_view", claim_id=claim_id))


    @app.route("/chat/<int:claim_id>/stream")
    @login_required
    def chat_stream(claim_id):
        import time as _time
        user_id = session["user_id"]

        def _check_access():
            conn = connect_db()
            claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
            if not claim:
                conn.close()
                return False, None
            owner_id = conn.execute(
                "SELECT user_id FROM posts WHERE id=?", (claim["found_post_id"],)
            ).fetchone()["user_id"]
            conn.close()
            return user_id in (claim["claimer_user_id"], owner_id), claim

        ok, _ = _check_access()
        if not ok:
            return Response("data: {}\n\n", status=403, mimetype="text/event-stream")

        def _generate():
            last_id = 0
            conn = connect_db()
            rows = conn.execute(
                "SELECT m.id, m.sender_id, m.message, m.created_at, u.full_name, u.avatar "
                "FROM chat_messages m JOIN users u ON m.sender_id=u.id "
                "WHERE m.claim_id=? ORDER BY m.id ASC", (claim_id,)
            ).fetchall()
            conn.execute(
                "UPDATE chat_messages SET is_read=1 WHERE claim_id=? AND sender_id!=?",
                (claim_id, user_id)
            )
            conn.commit()
            conn.close()
            if rows:
                last_id = rows[-1]["id"]
                for r in rows:
                    yield f"data: {json.dumps(dict(r))}\n\n"
            while True:
                _time.sleep(2)
                conn = connect_db()
                new_rows = conn.execute(
                    "SELECT m.id, m.sender_id, m.message, m.created_at, u.full_name, u.avatar "
                    "FROM chat_messages m JOIN users u ON m.sender_id=u.id "
                    "WHERE m.claim_id=? AND m.id>? ORDER BY m.id ASC",
                    (claim_id, last_id)
                ).fetchall()
                if new_rows:
                    conn.execute(
                        "UPDATE chat_messages SET is_read=1 WHERE claim_id=? AND sender_id!=? AND id>?",
                        (claim_id, user_id, last_id)
                    )
                    conn.commit()
                    last_id = new_rows[-1]["id"]
                conn.close()
                for r in new_rows:
                    yield f"data: {json.dumps(dict(r))}\n\n"
                yield ": keepalive\n\n"

        return Response(
            stream_with_context(_generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )


    @app.route("/chat/<int:claim_id>/messages")
    @login_required
    def chat_poll(claim_id):
        after_id = int(request.args.get("after", 0))
        conn = connect_db()
        claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not claim:
            conn.close()
            return jsonify({"messages": []}), 404
        found_owner_id = conn.execute("SELECT user_id FROM posts WHERE id=?", (claim["found_post_id"],)).fetchone()["user_id"]
        user_id = session["user_id"]
        if user_id not in (claim["claimer_user_id"], found_owner_id):
            conn.close()
            return jsonify({"messages": []}), 403
        rows = conn.execute("""
            SELECT m.id, m.sender_id, m.message, m.created_at, u.full_name, u.avatar
            FROM chat_messages m JOIN users u ON m.sender_id = u.id
            WHERE m.claim_id=? AND m.id > ? ORDER BY m.id ASC
        """, (claim_id, after_id)).fetchall()
        conn.execute("UPDATE chat_messages SET is_read=1 WHERE claim_id=? AND sender_id!=? AND id>?",
                     (claim_id, user_id, after_id))
        conn.commit()
        conn.close()
        return jsonify({"messages": [dict(r) for r in rows]})
