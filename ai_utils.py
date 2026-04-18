import os
import json
import base64

try:
    import anthropic as _anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


def claude_analyze_claim(found_post, claim_description, lost_post=None):
    """Phân tích claim bằng Claude AI. Trả về (score, reason) hoặc (None, None)."""
    if not HAS_ANTHROPIC:
        return None, None
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None, None

    lost_info = ""
    if lost_post:
        lost_info = (
            f"\n\nBài đăng mất đồ liên quan:\n"
            f"- Tiêu đề: {lost_post['title']}\n"
            f"- Mô tả: {(lost_post['description'] or 'Không có')[:300]}"
        )

    prompt = f"""Bạn là hệ thống xác minh thông minh cho website tìm đồ thất lạc PTIT Lost & Found.

Bài đăng đồ NHẶT ĐƯỢC:
- Tiêu đề: {found_post['title']}
- Danh mục: {found_post['category']}
- Mô tả: {(found_post['description'] or 'Không có')[:300]}
- Địa điểm: {found_post['location']}, {found_post.get('city', '') or ''}
- Gợi ý xác thực (công khai): {found_post.get('verification_hint', '') or 'Không có'}
{lost_info}

Người dùng khẳng định đây là đồ của họ và mô tả:
"{claim_description}"

Hãy phân tích xem người này có phải chủ thực sự không. Cho điểm từ 0-100:
- 80-100: Rõ ràng là chủ (chi tiết cụ thể, khớp chính xác)
- 60-79: Nhiều khả năng là chủ
- 40-59: Có thể, nên xem xét thêm
- 0-39: Không đủ bằng chứng

Chỉ trả về JSON, không có text khác: {{"score": <số 0-100>, "reason": "<1 câu lý do bằng tiếng Việt>"}}"""

    try:
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or None
        client = (_anthropic.Anthropic(api_key=api_key, base_url=base_url)
                  if base_url else _anthropic.Anthropic(api_key=api_key))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system="Bạn là hệ thống phân tích xác minh. Chỉ trả về JSON thuần túy.",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        result = json.loads(raw)
        score = min(100, max(0, int(result.get("score", 0))))
        reason = str(result.get("reason", ""))
        return score, reason
    except Exception as e:
        print(f"[AI] claude_analyze_claim error: {type(e).__name__}: {e}")
        return None, None


def claude_analyze_image(image_path):
    """Phân tích ảnh bằng Claude Vision. Trả về dict gợi ý hoặc None."""
    if not HAS_ANTHROPIC:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        with open(image_path, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(image_path)[1].lower().lstrip(".")
        media_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                      "png": "image/png", "gif": "image/gif"}.get(ext, "image/jpeg")
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or None
        client = (_anthropic.Anthropic(api_key=api_key, base_url=base_url)
                  if base_url else _anthropic.Anthropic(api_key=api_key))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_data}},
                {"type": "text", "text": (
                    "Phân tích ảnh vật phẩm thất lạc này. Trả về JSON thuần túy:\n"
                    '{"category":"<CCCD/Thẻ SV | Ví/Túi | Chìa khóa | Điện thoại | Thẻ xe | '
                    'Laptop/Máy tính | Quần áo | Sách/Vở | Tai nghe | Khác>",'
                    '"post_type":"<lost hoặc found hoặc empty>",'
                    '"description_hint":"<1-2 câu mô tả bằng tiếng Việt>",'
                    '"keywords":"<2-3 từ khóa phân cách bởi dấu phẩy>"}'
                )}
            ]}]
        )
        raw = response.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[AI] claude_analyze_image error: {type(e).__name__}: {e}")
        return None
