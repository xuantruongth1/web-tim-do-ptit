"""Routes: analyze_image_api, check_voucher."""
import os
from datetime import datetime
from flask import request, session, jsonify
from database import connect_db
from decorators import login_required
from utils import allowed_file, save_uploaded_file
from ai_utils import claude_analyze_image
from settings_utils import get_vip_packages


def register_routes(app, _rate):

    @app.route("/api/analyze-image", methods=["POST"])
    @login_required
    def analyze_image_api():
        if "image" not in request.files:
            return jsonify({"error": "no_file"}), 400
        file = request.files["image"]
        if not file or not allowed_file(file.filename):
            return jsonify({"error": "invalid_file"}), 400
        filename = save_uploaded_file(file)
        if not filename:
            return jsonify({"error": "save_failed"}), 500
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        result = claude_analyze_image(image_path)
        try:
            os.remove(image_path)
        except Exception:
            pass
        if result:
            return jsonify(result)
        return jsonify({"error": "ai_unavailable"}), 503


    @app.route("/api/voucher/check", methods=["POST"])
    @login_required
    def check_voucher():
        code = request.form.get("code", "").strip().upper()
        pkg  = request.form.get("package_key", "").strip()
        if not code:
            return jsonify({"valid": False, "message": "Nhập mã voucher"})
        conn = connect_db()
        v = conn.execute("""
            SELECT * FROM vouchers WHERE code=? AND is_active=1
            AND (valid_from IS NULL OR valid_from <= ?)
            AND (valid_until IS NULL OR valid_until >= ?)
        """, (code, str(datetime.now()), str(datetime.now()))).fetchone()
        conn.close()
        if not v:
            return jsonify({"valid": False, "message": "Mã không hợp lệ hoặc đã hết hạn"})
        if v["max_uses"] > 0 and v["used_count"] >= v["max_uses"]:
            return jsonify({"valid": False, "message": "Mã đã hết lượt sử dụng"})
        if v["applicable_packages"] and pkg and pkg not in v["applicable_packages"].split(","):
            return jsonify({"valid": False, "message": "Mã không áp dụng cho gói này"})
        pkgs = get_vip_packages()
        original = pkgs.get(pkg, {}).get("price", 0) if pkg else 0
        if v["discount_type"] == "percent":
            discount = int(original * v["discount_value"] / 100)
        else:
            discount = v["discount_value"]
        final_price = max(0, original - discount)
        return jsonify({
            "valid": True,
            "message": f"Giảm {'{}%'.format(v['discount_value']) if v['discount_type']=='percent' else '{:,}đ'.format(v['discount_value'])}",
            "discount_type": v["discount_type"],
            "discount_value": v["discount_value"],
            "final_price": final_price,
            "original_price": original,
        })
