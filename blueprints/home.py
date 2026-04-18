"""Routes: home, pricing, support_project."""
from flask import render_template
from database import connect_db
from utils import downgrade_expired_priorities
from settings_utils import get_vip_packages


def register_routes(app, _rate):

    @app.route("/")
    def home():
        downgrade_expired_priorities()
        conn = connect_db()
        lost_count    = conn.execute("SELECT COUNT(*) AS c FROM posts WHERE post_type='lost'  AND status='active'").fetchone()["c"]
        found_count   = conn.execute("SELECT COUNT(*) AS c FROM posts WHERE post_type='found' AND status='active'").fetchone()["c"]
        total_users   = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        resolved_count = conn.execute("SELECT COUNT(*) AS c FROM posts WHERE status='resolved'").fetchone()["c"]
        urgent_posts  = conn.execute(
            "SELECT p.*, u.full_name FROM posts p LEFT JOIN users u ON p.user_id=u.id "
            "WHERE p.status='active' AND p.priority>0 ORDER BY p.priority DESC, p.id DESC LIMIT 6"
        ).fetchall()
        latest_lost   = conn.execute(
            "SELECT p.*, u.full_name FROM posts p LEFT JOIN users u ON p.user_id=u.id "
            "WHERE p.post_type='lost' AND p.status='active' ORDER BY p.id DESC LIMIT 6"
        ).fetchall()
        latest_found  = conn.execute(
            "SELECT p.*, u.full_name FROM posts p LEFT JOIN users u ON p.user_id=u.id "
            "WHERE p.post_type='found' AND p.status='active' ORDER BY p.id DESC LIMIT 8"
        ).fetchall()
        resolved_posts = conn.execute(
            "SELECT p.*, u.full_name FROM posts p LEFT JOIN users u ON p.user_id=u.id "
            "WHERE p.status='resolved' ORDER BY p.id DESC LIMIT 5"
        ).fetchall()
        conn.close()
        return render_template("home.html",
            lost_count=lost_count, found_count=found_count,
            total_users=total_users, resolved_count=resolved_count,
            urgent_posts=urgent_posts, latest_lost_posts=latest_lost,
            latest_found_posts=latest_found, resolved_posts=resolved_posts)


    @app.route("/pricing")
    def pricing():
        return render_template("pricing.html", packages=get_vip_packages())


    @app.route("/ho-tro-du-an")
    def support_project():
        return render_template("support.html")
