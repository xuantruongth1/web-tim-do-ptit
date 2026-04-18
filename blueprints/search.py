"""Routes: quick_search_api, search, match."""
from flask import request, session, render_template
from flask import jsonify
from database import connect_db
from utils import normalize_vn, downgrade_expired_priorities, match_score
from decorators import login_required
from config import PER_PAGE


def register_routes(app, _rate):

    @app.route("/api/quick-search")
    def quick_search_api():
        q = request.args.get("q", "").strip()
        if len(q) < 2:
            return jsonify([])
        q_norm = normalize_vn(q)
        conn = connect_db()
        rows = conn.execute("""
            SELECT p.id, p.title, p.post_type, p.category, p.location, p.image,
                   p.priority, p.created_at, u.full_name
            FROM posts p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE p.status = 'active'
              AND (norm_vn(p.title) LIKE ? OR norm_vn(p.description) LIKE ? OR norm_vn(p.category) LIKE ?)
            ORDER BY p.priority DESC, p.id DESC
            LIMIT 12
        """, (f"%{q_norm}%", f"%{q_norm}%", f"%{q_norm}%")).fetchall()
        conn.close()
        results = []
        for r in rows:
            score = 0
            if q_norm in normalize_vn(r["title"] or ""):
                score += 60
            if q_norm in normalize_vn(r["category"] or ""):
                score += 30
            if q_norm in normalize_vn(r["location"] or ""):
                score += 20
            score = min(score + 10, 100)
            results.append({
                "id": r["id"],
                "title": r["title"],
                "post_type": r["post_type"],
                "category": r["category"] or "",
                "location": r["location"] or "",
                "image": r["image"] or "",
                "priority": r["priority"],
                "full_name": r["full_name"] or "",
                "score": score,
            })
        results.sort(key=lambda x: x["score"], reverse=True)
        return jsonify(results)


    @app.route("/search", methods=["GET", "POST"])
    def search():
        downgrade_expired_priorities()
        page = request.args.get("page", 1, type=int)
        posts = []
        keyword = category = city = post_type = ""
        total = total_pages = 0

        if request.method == "POST":
            keyword   = request.form.get("keyword", "").strip()
            category  = request.form.get("category", "").strip()
            city      = request.form.get("city", "").strip()
            post_type = request.form.get("post_type", "").strip()
            page = 1
        else:
            keyword   = request.args.get("keyword", "").strip()
            category  = request.args.get("category", "").strip()
            city      = request.args.get("city", "").strip()
            post_type = request.args.get("post_type", "").strip()

        if keyword or category or city or post_type:
            base_query = """
                FROM posts p LEFT JOIN users u ON p.user_id = u.id
                WHERE p.status='active'
            """
            params = []
            if keyword:
                kw_norm = normalize_vn(keyword)
                base_query += " AND (norm_vn(p.title) LIKE ? OR norm_vn(p.description) LIKE ? OR norm_vn(p.location) LIKE ?)"
                params.extend([f"%{kw_norm}%", f"%{kw_norm}%", f"%{kw_norm}%"])
            if category:
                base_query += " AND p.category LIKE ?"
                params.append(f"%{category}%")
            if city:
                base_query += " AND p.city LIKE ?"
                params.append(f"%{city}%")
            if post_type:
                base_query += " AND p.post_type = ?"
                params.append(post_type)

            conn = connect_db()
            total = conn.execute(f"SELECT COUNT(*) as c {base_query}", params).fetchone()["c"]
            total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
            order_offset = " ORDER BY p.priority DESC, p.id DESC LIMIT ? OFFSET ?"
            posts = conn.execute(
                f"SELECT p.*, u.full_name {base_query}{order_offset}",
                params + [PER_PAGE, (page - 1) * PER_PAGE]
            ).fetchall()
            conn.close()

        return render_template(
            "search.html",
            posts=posts, keyword=keyword, category=category,
            city=city, post_type=post_type,
            page=page, total_pages=total_pages, total=total,
        )


    @app.route("/match")
    @login_required
    def match():
        conn = connect_db()
        user_id  = session["user_id"]
        is_admin = session.get("role") == "admin"

        lost_posts_all  = conn.execute("SELECT * FROM posts WHERE post_type='lost'  AND status='active'").fetchall()
        found_posts_all = conn.execute("SELECT * FROM posts WHERE post_type='found' AND status='active'").fetchall()
        conn.close()

        results = []
        for lost_item in lost_posts_all:
            for found_item in found_posts_all:
                if not is_admin and lost_item["user_id"] != user_id and found_item["user_id"] != user_id:
                    continue
                score = match_score(lost_item, found_item)
                if score >= 30:
                    results.append((lost_item, found_item, score))

        results.sort(key=lambda x: x[2], reverse=True)
        results = results[:30]
        return render_template("match.html", results=results, is_admin=is_admin)
