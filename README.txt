================================================================================
  PTIT LOST & FOUND — HỆ THỐNG TÌM ĐỒ THẤT LẠC TRƯỜNG PTIT
  Phiên bản: 2.0 Modular Blueprint | Python Flask + SQLite + Claude AI
================================================================================


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MỤC LỤC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1.  Tổng quan dự án
  2.  Tech Stack
  3.  Cài đặt & chạy nhanh
  4.  Cấu hình (.env)
  5.  Tài khoản mặc định
  6.  Kiến trúc thư mục
  7.  Cơ sở dữ liệu (14 bảng)
  8.  Phân quyền người dùng
  9.  Chức năng: Người dùng thường
  10. Chức năng: Hệ thống AI
  11. Chức năng: Admin Panel
  12. Luồng hoạt động chính
  13. API Endpoints (JSON)
  14. Bảo mật
  15. Email & Thông báo
  16. Gói VIP
  17. Cấu hình nâng cao (site_settings)
  18. Changelog — v2.0 Modular


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. TỔNG QUAN DỰ ÁN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PTIT Lost & Found là web ứng dụng giúp sinh viên và cán bộ trường PTIT
  đăng tin mất đồ / nhặt được đồ, tìm kiếm & kết nối với nhau, xác minh
  chủ sở hữu qua AI, và liên lạc trực tiếp qua chat.

  Điểm nổi bật:
  - Đăng tin mất/nhặt đồ với hình ảnh và xác thực bí mật
  - AI Claude phân tích ảnh gợi ý danh mục & mô tả khi tạo bài
  - Hệ thống gợi ý ghép cặp tự động (lost ↔ found)
  - AI Claude chấm điểm xác minh khi người dùng nhận đồ (0–100)
  - Hồ sơ cá nhân: đổi thông tin, avatar, mật khẩu
  - Xác minh email bắt buộc trước khi đăng bài (ngoại trừ admin/moderator)
  - Hệ thống thông báo realtime (badge đỏ trên nav)
  - Hệ thống gói VIP (Nổi bật / Ưu tiên / Tìm gấp)
  - Chat riêng tư sau khi xác minh thành công
  - Admin dashboard đầy đủ: duyệt bài, quản lý user, doanh thu, log


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  2. TECH STACK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Backend    : Python 3.11+, Flask >= 3.0.0
  Database   : SQLite3 (file: database.db), raw SQL với sqlite3.Row
  AI         : Anthropic Claude API (claude-haiku-4-5-20251001)
  Email      : smtplib + Gmail SMTP (App Password)
  Auth       : Flask Session (filesystem) + werkzeug password hashing
  CSRF       : Flask-WTF (CSRFProtect) — toàn bộ form POST được bảo vệ
  Session    : flask-session (filesystem backend, signed)
  Rate Limit : flask-limiter (tắt gracefully nếu không có)
  Image      : Pillow — resize ảnh upload (max 800px), nén chất lượng cao
  Frontend   : Jinja2 templates + CSS tùy chỉnh (static/css/style.css)
  Real-time  : Server-Sent Events (SSE) + polling fallback cho chat

  Thư viện Python (requirements.txt):
    flask>=3.0.0
    werkzeug>=3.0.0
    python-dotenv>=1.0.0
    anthropic>=0.40.0
    flask-limiter>=3.5.0
    flask-session>=0.8.0
    flask-wtf>=1.2.0
    Pillow>=10.0.0


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  3. CÀI ĐẶT & CHẠY NHANH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Yêu cầu: Python 3.11+

  Bước 1 — Cài thư viện:
    pip install -r requirements.txt

  Bước 2 — Cấu hình môi trường:
    Sao chép .env.example thành .env rồi điền thông tin (xem mục 4)

  Bước 3 — Chạy ứng dụng:
    python app.py

  Bước 4 — Mở trình duyệt:
    http://127.0.0.1:5000

  Lần chạy đầu tiên tự động:
  - Tạo database.db với toàn bộ 14 bảng + migration tự động
  - Seed 12 danh mục mặc định
  - Tạo tài khoản admin mặc định (xem mục 5)
  - Tạo thư mục uploads/, flask_sessions/ nếu chưa có


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  4. CẤU HÌNH (.env)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  File .env cần có các biến sau:

  ┌─────────────────────────────────────────────────────────────┐
  │  SECRET_KEY=<chuỗi ngẫu nhiên dài>                         │
  │  # Tạo bằng: python -c "import secrets; print(secrets.token_hex(32))"
  │                                                             │
  │  FLASK_DEBUG=false                                          │
  │                                                             │
  │  ANTHROPIC_API_KEY=sk-ant-api03-...                         │
  │  # Lấy tại: https://console.anthropic.com/                  │
  │  # ANTHROPIC_BASE_URL=  (để trống nếu dùng key chính thức) │
  │                                                             │
  │  MAIL_SERVER=smtp.gmail.com                                 │
  │  MAIL_PORT=587                                              │
  │  MAIL_USERNAME=your_email@gmail.com                         │
  │  MAIL_PASSWORD=xxxx xxxx xxxx xxxx   (Gmail App Password)  │
  │  MAIL_FROM=PTIT Lost & Found <your_email@gmail.com>         │
  └─────────────────────────────────────────────────────────────┘

  Lưu ý Gmail App Password:
    myaccount.google.com → Bảo mật → Xác minh 2 bước → Mật khẩu ứng dụng

  Tất cả cấu hình đều tùy chọn:
  - Nếu không có ANTHROPIC_API_KEY: AI fallback sang rule-based tự động.
  - Nếu không có MAIL_*: email bị bỏ qua silently, xác minh email bỏ qua.
  - Nếu không có SECRET_KEY: dùng key mặc định (KHÔNG an toàn cho production).


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  5. TÀI KHOẢN MẶC ĐỊNH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Admin mặc định (tự tạo khi chạy lần đầu):
    username : admin
    password : admin123

  !!! ĐỔI MẬT KHẨU NGAY SAU KHI DEPLOY !!!
  Vào Admin Panel → Quản lý người dùng → admin → Reset mật khẩu

  Lưu ý: Admin và Moderator được miễn xác minh email khi đăng bài.
  Người dùng thường phải xác minh email trước khi đăng bài đầu tiên.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  6. KIẾN TRÚC THƯ MỤC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ptit_lost_found_upgrade/
  ├── app.py                 # Entry point mỏng — đăng ký blueprint, extension
  ├── config.py              # Hằng số: UPLOAD_FOLDER, PER_PAGE, VIP defaults
  ├── database.py            # Kết nối DB, create_tables(), migration, seed data
  ├── decorators.py          # @login_required, @admin_required, @moderator_required
  ├── utils.py               # normalize_vn, match_score, save_uploaded_file,
  │                          #   check_banned_words, log_admin_action, time_ago
  ├── ai_utils.py            # claude_analyze_claim(), claude_analyze_image()
  ├── email_utils.py         # send_email() — bất đồng bộ qua threading
  ├── settings_utils.py      # get_setting(), get_vip_packages()
  ├── extensions.py          # Khai báo extension dùng chung (tham chiếu)
  ├── requirements.txt       # Thư viện Python
  ├── .env                   # Biến môi trường (KHÔNG commit lên git)
  ├── database.db            # SQLite database (tự tạo)
  ├── app_legacy.py          # Phiên bản cũ monolithic — chỉ tham khảo
  │
  ├── blueprints/            # Tách route theo chức năng
  │   ├── __init__.py
  │   ├── auth.py            # Đăng ký, xác minh email, đăng nhập, đổi mật khẩu
  │   ├── home.py            # Trang chủ, bảng giá, trang hỗ trợ
  │   ├── profile.py         # Hồ sơ, avatar, đổi mật khẩu, bài đăng của tôi
  │   ├── posts.py           # Tạo/sửa bài, danh sách lost/found/premium
  │   ├── search.py          # Tìm kiếm nâng cao, quick-search API, ghép cặp
  │   ├── claims.py          # Gửi claim, quản lý claim nhận/gửi
  │   ├── chat.py            # Chat, SSE stream, polling tin nhắn
  │   ├── payment.py         # Thanh toán gói VIP
  │   ├── api.py             # /api/analyze-image, /api/voucher/check
  │   └── admin.py           # Toàn bộ /admin/* (~45 route)
  │
  ├── templates/             # 39 file HTML (Jinja2)
  │   ├── base.html              # Layout chính cho trang user (với CSRF JS)
  │   ├── base_admin.html        # Layout cho admin panel (với CSRF JS)
  │   ├── base_dashboard.html    # Layout dashboard dạng sidebar (với CSRF JS)
  │   ├── home.html / login.html / register.html
  │   ├── create_post.html       # Tạo bài — sử dụng base_dashboard
  │   ├── edit_post.html         # Sửa bài đăng
  │   ├── post_detail.html       # Chi tiết bài + claim modal + chat
  │   ├── posts.html             # Danh sách lost/found/premium
  │   ├── search.html            # Kết quả tìm kiếm
  │   ├── match.html             # Gợi ý ghép cặp
  │   ├── profile.html           # Trang cá nhân (tabs: thông tin / bảo mật)
  │   ├── pricing.html / payment.html
  │   ├── my_posts.html / my_claims.html / my_received_claims.html
  │   ├── my_chats.html / chat.html
  │   ├── post_success.html
  │   ├── change_password_forced.html
  │   ├── admin.html             # Dashboard admin
  │   ├── admin_posts.html / admin_users.html / admin_payments.html
  │   ├── admin_claims.html / admin_revenue.html / admin_logs.html
  │   ├── admin_settings.html / admin_categories.html
  │   ├── admin_comments.html / admin_announcements.html
  │   ├── admin_vouchers.html / admin_reports.html
  │   ├── admin_bulk_email.html / admin_user_profile.html
  │   └── support.html
  │
  └── static/
      ├── css/style.css          # Stylesheet chính
      ├── images/logo.png        # Logo
      ├── images/samples/        # 6 ảnh mẫu SVG (cccd, wallet, key, phone, ...)
      ├── uploads/               # Ảnh bài đăng (tự tạo)
      │   └── avatars/           # Ảnh đại diện user (tự tạo)
      └── [flask_sessions/]      # Session lưu trên filesystem


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  7. CƠ SỞ DỮ LIỆU (14 BẢNG)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  users
    id, full_name, username, password (hash), role (user|admin|moderator),
    email, email_verified (0|1), email_token,
    avatar (filename), bio (tối đa 300 ký tự),
    is_locked (0|1), force_password_change (0|1), created_at

  posts
    id, title, category, description, event_date, location, city, campus,
    contact, image (filename), post_type (lost|found),
    status (pending_review|active|rejected|hidden|resolved),
    priority (0–3, VIP level), package_key,
    vip_started_at, vip_expires_at,
    verification_hint (công khai), private_verification_note (bí mật),
    tags (comma-separated, tối đa 3),
    is_pinned (0|1), pin_expires_at, is_scam_warned (0|1), label,
    user_id, created_at

  claims
    id, lost_post_id (nullable), found_post_id, claimer_user_id,
    claim_description, ai_score (0–100), ai_reason,
    status (pending|matched|low_match|rejected|owner_confirmed),
    owner_confirmed (0|1), contact_unlocked (0|1),
    owner_reviewed_at, created_at

  payments
    id, user_id, post_id, package_key, package_name, amount,
    transfer_content, status (pending|paid|rejected),
    payment_proof (filename), refunded (0|1), refund_note,
    confirmed_by, created_at, confirmed_at

  chat_messages
    id, claim_id, sender_id, message, is_read (0|1), created_at

  comments
    id, post_id, user_id, content, created_at

  notifications
    id, user_id, type (comment|other), message, link, is_read (0|1), created_at

  reports
    id, post_id, reporter_user_id, content,
    status (pending|approved|rejected), admin_note,
    created_at, reviewed_at, reviewed_by

  admin_logs
    id, admin_id, admin_username, action, target_type, target_id, detail,
    created_at

  site_settings    : key (PRIMARY), value, updated_at
  categories       : id, name, icon (emoji), sort_order, created_at
  announcements    : id, title, content, type, show_from, show_until,
                     is_active, created_at, created_by
  banned_words     : id, word (UNIQUE), created_at
  vouchers         : id, code (UNIQUE), discount_type (percent|fixed),
                     discount_value, max_uses, used_count,
                     valid_from, valid_until, applicable_packages,
                     is_active, created_at, note

  Migration tự động:
    Mỗi lần khởi động, hệ thống chạy ALTER TABLE IF NOT EXISTS cho từng
    cột mới — database cũ được nâng cấp tự động không mất dữ liệu.

  Status bài đăng (posts.status):
    pending_review → active → resolved
                   → rejected
                   → hidden  → active (reactivate)

  Status claim:
    pending → matched (AI ≥ 50) | low_match (AI < 50)
            → owner_confirmed  (chủ xác nhận)
            → rejected         (chủ từ chối)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  8. PHÂN QUYỀN NGƯỜI DÙNG
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Ba vai trò: user | admin | moderator

  ┌──────────────────────────────────────┬──────┬───────┬───────────┐
  │ Quyền                                │ User │ Mod   │ Admin     │
  ├──────────────────────────────────────┼──────┼───────┼───────────┤
  │ Đăng bài (cần email xác minh)       │  ✓*  │  ✓    │  ✓        │
  │ Sửa/xóa bài của mình                │  ✓   │  ✓    │  ✓        │
  │ Tìm kiếm & xem bài                  │  ✓   │  ✓    │  ✓        │
  │ Gửi claim xác minh                  │  ✓   │  ✓    │  ✓        │
  │ Chat sau khi được xác nhận          │  ✓   │  ✓    │  ✓        │
  │ Bình luận, tố cáo                   │  ✓   │  ✓    │  ✓        │
  │ Cập nhật hồ sơ & avatar             │  ✓   │  ✓    │  ✓        │
  │ Đổi mật khẩu                        │  ✓   │  ✓    │  ✓        │
  │ Xem điểm match trên /match          │  ✗   │  ✗    │  ✓        │
  │ Duyệt / ẩn / xóa bài               │  ✗   │  ✓    │  ✓        │
  │ Quản lý người dùng                  │  ✗   │  ✗    │  ✓        │
  │ Xác nhận thanh toán VIP             │  ✗   │  ✗    │  ✓        │
  │ Xem doanh thu & log                 │  ✗   │  ✗    │  ✓        │
  │ Quản lý cài đặt hệ thống            │  ✗   │  ✗    │  ✓        │
  │ Gửi email hàng loạt                 │  ✗   │  ✗    │  ✓        │
  └──────────────────────────────────────┴──────┴───────┴───────────┘

  (*) User thường phải có email xác minh mới được đăng bài.
      Admin/Moderator miễn điều kiện này.

  Bảo vệ route:
    @login_required      — redirect về /login nếu chưa đăng nhập
    @admin_required      — redirect nếu không phải admin
    @moderator_required  — redirect nếu không phải admin hoặc moderator


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  9. CHỨC NĂNG: NGƯỜI DÙNG THƯỜNG
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [Đăng ký / Đăng nhập]
  - Đăng ký với username, họ tên, mật khẩu (≥6 ký tự), email (tùy chọn)
  - Giới hạn: 5 lần đăng ký/phút, 10 lần đăng nhập/phút (flask-limiter)
  - Tài khoản bị khóa sẽ không thể đăng nhập
  - Có thể bị yêu cầu đổi mật khẩu bắt buộc (do admin đặt flag)
  - Sau đăng ký: gửi email xác minh (nếu có email)

  [Xác minh email]
  - Link xác minh gửi vào email sau khi đăng ký
  - Link dùng một lần, vô hiệu sau khi click
  - Có thể gửi lại từ trang hồ sơ nếu chưa nhận được
  - Bắt buộc để đăng bài (user thường)

  [Hồ sơ cá nhân — /profile]
  - Tab "Thông tin": cập nhật họ tên, email, giới thiệu bản thân (tối đa 300 ký tự)
  - Tab "Bảo mật": đổi mật khẩu (kiểm tra mật khẩu hiện tại, cần ≥6 ký tự)
  - Nhấn vào avatar để đổi ảnh (upload → Pillow resize 300×300px)
  - Thay đổi email cần xác minh lại
  - Hiển thị thống kê: tổng bài, bài đang hoạt động, bài đã tìm lại, lần xác minh
  - Badge trạng thái AI (cấu hình hay chưa)

  [Đăng bài (Create Post) — /create]
  - Yêu cầu email đã xác minh (ngoại trừ admin/moderator)
  - Layout dashboard với thanh sidebar điều hướng
  - Điền: tiêu đề, danh mục, mô tả, ngày xảy ra, địa điểm, thành phố, cơ sở, liên hệ
  - Loại bài: lost (mất đồ) hoặc found (nhặt được)
  - Gợi ý xác thực (công khai): câu hỏi/dấu hiệu để người nhận trả lời [BẮT BUỘC]
  - Ghi chú bí mật (private): chỉ chủ bài nhìn thấy, tự kiểm tra [BẮT BUỘC]
  - Tags: tối đa 3 từ khóa phụ (input chip UI)
  - Upload ảnh tùy chỉnh (Pillow resize max 800px) HOẶC chọn ảnh mẫu SVG
  - AI tự động phân tích ảnh → gợi ý danh mục + mô tả + tags (nếu có API key)
  - Chọn gói VIP (chỉ cho bài mất đồ, xem mục 16)
  - Bài vào trạng thái pending_review, chờ admin/moderator duyệt

  [Sửa bài — /edit/<post_id>]
  - Sửa tiêu đề, danh mục, mô tả, địa điểm, liên hệ, ảnh, hint, tags
  - Chỉ chủ bài hoặc admin được sửa

  [Tìm kiếm — /search]
  - Tìm theo từ khóa (tiêu đề, mô tả, địa điểm) — hỗ trợ có dấu/không dấu
  - Lọc: danh mục, thành phố, loại bài (mất/nhặt)
  - Phân trang 12 bài/trang
  - Autocomplete API (/api/quick-search?q=) trả JSON cho dropdown

  [Gợi ý ghép cặp — /match]
  - Hệ thống tự động ghép bài mất ↔ bài nhặt theo điểm tương đồng
  - User thường: chỉ thấy cặp liên quan đến bài của mình
  - Admin: thấy tất cả cặp (kèm điểm số chi tiết)
  - Ngưỡng hiển thị: ≥ 30 điểm; tối đa 30 cặp, sắp xếp giảm dần

  [Xác minh nhận đồ (Claim) — POST /claim/<found_post_id>]
  - Nhấn "Đây là đồ của tôi" trên trang chi tiết bài nhặt được
  - Điền mô tả chi tiết chứng minh quyền sở hữu
  - Tùy chọn: liên kết bài mất đồ của mình để tăng điểm
  - Chống spam: 1 claim/user/bài trong 1 giờ
  - AI Claude chấm điểm 0–100, đưa lý do bằng tiếng Việt
    * ≥ 50 điểm → matched, thông tin liên hệ mở khóa tự động
    * < 50 điểm → low_match, liên hệ vẫn ẩn chờ chủ xét
  - Nếu AI không khả dụng: fallback rule-based (xem mục 10)

  [Quản lý Claim]
  - /my-claims          : xem các claim tôi đã gửi + trạng thái + điểm AI
  - /my-received-claims : xem claim người khác gửi tới bài nhặt của mình
      → Xác nhận đúng người: status = owner_confirmed, mở chat
      → Từ chối: status = rejected

  [Chat — /chat/<claim_id>]
  - Chỉ mở sau khi owner xác nhận claim (owner_confirmed)
  - Chat 1-1 giữa người mất và người nhặt
  - Real-time qua Server-Sent Events (SSE) hoặc polling fallback
  - Đánh dấu đã đọc tự động khi mở chat

  [Quản lý bài — /my-posts]
  - Xem tất cả bài của mình với trạng thái + gói VIP
  - Đánh dấu đã tìm được (resolved)
  - Xóa bài của mình

  [Bình luận]
  - Bình luận công khai trên bài đăng
  - Sửa/xóa bình luận của mình
  - Từ cấm bị chặn, thông báo chủ bài qua email

  [Tố cáo]
  - Báo cáo bài đăng nghi ngờ lừa đảo tại /post/<id>/report
  - Admin xem xét → gắn cờ "⚠️ Đã bị tố cáo" trên bài

  [Thông báo]
  - Badge đỏ trên nav khi có claim mới hoặc bình luận mới
  - Dropdown hiển thị 10 thông báo gần nhất
  - Nhấn "Đã đọc hết" để xóa badge


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  10. CHỨC NĂNG: HỆ THỐNG AI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Model: claude-haiku-4-5-20251001
  Cấu hình: ANTHROPIC_API_KEY trong .env
  Fallback: hoàn toàn tự động nếu AI không khả dụng

  [Phân tích ảnh — POST /api/analyze-image]
  Khi user upload ảnh lúc tạo bài, AI tự động:
  - Nhận diện danh mục (CCCD, Ví/Túi, Chìa khóa, Điện thoại, Thẻ xe,
    Laptop, Quần áo, Sách/Vở, Tai nghe, Khác)
  - Phân loại lost/found
  - Tạo mô tả 1-2 câu bằng tiếng Việt
  - Gợi ý 2-3 từ khóa
  - Kết quả hiển thị dạng banner "AI gợi ý", user có thể áp dụng hoặc bỏ qua
  - Endpoint được bảo vệ bằng CSRF token (X-CSRFToken header)

  [Chấm điểm xác minh — gọi khi submit Claim]
  AI nhận:
  - Thông tin bài nhặt được (tiêu đề, danh mục, mô tả, địa điểm, hint)
  - Mô tả claim của người nhận
  - Bài mất đồ liên kết (nếu có)
  AI trả về:
  - score: 0–100
  - reason: 1 câu lý do tiếng Việt
  Ý nghĩa điểm:
    80–100 : Rõ ràng là chủ sở hữu
    60–79  : Nhiều khả năng là chủ
    40–59  : Có thể, nên xem xét thêm
    0–39   : Không đủ bằng chứng
  Ngưỡng: điểm ≥ 50 → mở khóa thông tin liên hệ tự động

  [Fallback rule-based (match_score)]
  Khi AI không khả dụng:
    Tiêu đề khớp chính xác  : +40
    Tiêu đề chứa nhau       : +25
    Danh mục khớp           : +20
    Địa điểm khớp           : +20
    Thành phố khớp          : +10
    Từ khóa trong mô tả     : +5/từ (từ trong claim khớp mô tả bài)
    Tags chung              : +5/tag
    Tối đa: 100 điểm


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  11. CHỨC NĂNG: ADMIN PANEL (/admin/...)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [Dashboard — /admin]
  - Thống kê tổng: users, posts, active, resolved, pending, tỷ lệ match
  - Top 5 danh mục; danh sách bài chờ duyệt

  [Quản lý bài đăng — /admin/posts]
  - Lọc theo: trạng thái, loại bài, gói VIP, tìm theo tiêu đề/ID
  - Thao tác đơn lẻ: Duyệt / Từ chối / Ẩn / Tái kích hoạt / Xóa / Ghim / Gán nhãn
  - Thao tác hàng loạt (bulk): duyệt, từ chối, ẩn, xóa, resolved
  - Ghim bài (pin) lên đầu danh sách, có thể đặt thời hạn ghim

  [Quản lý VIP]
  - Gia hạn VIP thêm N ngày | Chuyển gói | Đặt ngày hết hạn tùy chỉnh
  - Đặt priority (0–10) thủ công | Cấp VIP miễn phí cho bài bất kỳ
  - VIP hết hạn tự động hạ priority = 0

  [Quản lý người dùng — /admin/users]
  - Danh sách user + số bài + số claim
  - Cấp/thu quyền admin, khóa/mở khóa tài khoản
  - Xem profile chi tiết: lịch sử bài, claim, thanh toán
  - Sửa thông tin: họ tên, email, vai trò
  - Reset mật khẩu (có thể bắt buộc đổi lần sau)
  - Xóa user (tùy chọn giữ/xóa bài của họ)

  [Xác nhận thanh toán — /admin/payments]
  - Lọc theo trạng thái: pending / paid / rejected
  - Xem ảnh biên lai chuyển khoản
  - Xác nhận → kích hoạt VIP | Từ chối | Hoàn tiền (hạ VIP về chuẩn)

  [Quản lý Claim — /admin/claims]
  - Xem tất cả claim, lọc theo trạng thái
  - Sửa trạng thái thủ công | Override điểm AI
  - Bật/tắt contact_unlocked

  [Doanh thu — /admin/revenue]
  - Tổng doanh thu theo gói, theo khoảng thời gian
  - Biểu đồ Chart.js (7/30 ngày)
  - Xuất CSV (/admin/export/revenue.csv)
  - API thống kê JSON (/admin/api/stats?period=7days|30days)

  [Nhật ký admin — /admin/logs]
  - Mọi thao tác admin: ai làm gì, với đối tượng nào, lúc mấy giờ
  - Phân trang 50 bản ghi/trang

  [Cài đặt hệ thống — /admin/settings]
  - Tên site, mô tả, thông tin liên hệ, thông tin ngân hàng
  - Cấu hình gói VIP: tên, giá, số ngày, priority, nhãn
  - Bật/tắt tính năng (VIP, AI, chat, bình luận)

  [Danh mục — /admin/categories]
  - Thêm/sửa/xóa; mỗi danh mục: tên + icon emoji + thứ tự

  [Thông báo hệ thống — /admin/announcements]
  - Banner thông báo trên trang chủ; loại: info/warning/success/danger
  - Đặt thời gian hiển thị (từ ngày X đến ngày Y)

  [Bình luận & Từ cấm — /admin/comments]
  - Xem và xóa bình luận vi phạm
  - Thêm/xóa từ cấm (áp dụng cả tiêu đề, mô tả bài và bình luận)

  [Tố cáo & Scam — /admin/reports]
  - Xem báo cáo, lọc theo trạng thái
  - Duyệt: gắn "⚠️ Đã bị tố cáo" | Bác: giữ nguyên bài

  [Mã giảm giá — /admin/vouchers]
  - Tạo voucher: giảm % hoặc giảm tiền cố định
  - Giới hạn lượt dùng, thời hạn hiệu lực, áp dụng cho gói cụ thể
  - Kiểm tra voucher: POST /api/voucher/check

  [Email hàng loạt — /admin/bulk-email]
  - Soạn email HTML
  - Gửi đến: tất cả user CÓ email, hoặc chỉ user chưa đăng bài


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  12. LUỒNG HOẠT ĐỘNG CHÍNH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  LUỒNG 1: Đăng ký → Xác minh email → Đăng bài

    1. User đăng ký tại /register (điền username, họ tên, mật khẩu, email)
    2. Hệ thống gửi email xác minh → User nhấn link → email_verified = 1
    3. User vào /create → điền thông tin + upload ảnh
       → AI phân tích ảnh → gợi ý danh mục "Ví/Túi"
    4. Submit → bài vào pending_review
    5. Admin/Moderator duyệt → status = active

  LUỒNG 2: Tìm đồ và xác minh

    [User B mất ví]
    1. Tìm trên /lost hoặc /search, hoặc vào /match để xem gợi ý tự động
    2. Nhấn "Đây là đồ của tôi" → điền claim mô tả chi tiết
    3. AI chấm điểm (VD: 82/100) → matched, liên hệ của người nhặt mở khóa
    4. Chủ bài (người nhặt) nhận email thông báo → vào /my-received-claims
    5. Xác nhận đúng người → owner_confirmed
    6. Chat mở tại /chat/<claim_id> → hẹn trả đồ

  LUỒNG 3: Đăng bài VIP

    1. User tạo bài "lost" → chọn gói (VD: "Tìm gấp" 30k)
    2. Hệ thống tạo lệnh thanh toán + nội dung chuyển khoản
    3. User chuyển khoản theo hướng dẫn + upload ảnh biên lai
    4. Admin vào /admin/payments → xác nhận → VIP kích hoạt
    5. Bài được priority = 3, hiển thị trên đầu danh sách premium
    6. Sau N ngày VIP hết hạn → priority tự về 0


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  13. API ENDPOINTS (JSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  GET  /api/quick-search?q=<keyword>
       → [{id, title, category, post_type, city, score}, ...]
       → Autocomplete, tối đa 12 kết quả. Cần đăng nhập.

  POST /api/analyze-image
       body: multipart/form-data, field: image
       headers: X-CSRFToken: <token>
       → {category, post_type, description_hint, keywords}
       → Lỗi: {error: "no_file"|"invalid_file"|"save_failed"|"ai_unavailable"}
       → Cần đăng nhập + CSRF token

  GET  /chat/<claim_id>/messages?after=<last_id>
       → {messages: [{id, sender_id, message, created_at, is_read}, ...]}
       → Polling fallback cho real-time chat

  GET  /chat/<claim_id>/stream
       → text/event-stream (SSE) cho real-time messages

  POST /api/voucher/check
       body: code, package_key
       headers: X-CSRFToken: <token>
       → {valid, discount_type, discount_value, final_price, original_price, message}
       → Cần đăng nhập + CSRF token

  GET  /admin/api/stats?period=7days|30days
       → {labels, posts, users, revenue}
       → Dữ liệu Chart.js trên trang revenue. Chỉ admin.

  POST /profile/update             → {ok, msg, email_changed}
  POST /profile/change-password    → {ok, msg}
  POST /profile/upload-avatar      → {ok, msg, avatar_url}
  POST /profile/resend-verify      → {ok, msg}
  POST /notifications/mark-read    → {ok: true}

  Tất cả POST API đều yêu cầu CSRF token qua:
  - Header X-CSRFToken (AJAX/fetch)
  - Hidden input csrf_token (HTML form)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  14. BẢO MẬT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  - Mật khẩu: hash bằng werkzeug.security (PBKDF2+SHA256), không lưu plaintext
  - SQL: parameterized queries (?) — chống SQL injection toàn bộ codebase
  - CSRF: Flask-WTF CSRFProtect — bảo vệ toàn bộ form POST và AJAX POST
    * HTML form: <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    * AJAX fetch: header X-CSRFToken tự động inject qua JS trong base templates
    * base.html, base_admin.html, base_dashboard.html đều có CSRF meta + JS
  - Session: flask-session (filesystem, có ký) — chống session forgery
  - File upload: kiểm tra extension, secure_filename() — chống path traversal
    * Pillow resize ảnh — giảm rủi ro ảnh độc hại
    * Avatar lưu trong uploads/avatars/ riêng biệt
  - Rate limiting: đăng ký 5/phút, đăng nhập 10/phút (flask-limiter)
  - Từ cấm: kiểm tra tiêu đề + mô tả + bình luận trước khi lưu
  - Chống spam claim: 1 claim/user/bài/giờ
  - Khóa tài khoản: admin lock user ngay lập tức
  - Forced password change: admin buộc user đổi mật khẩu khi đăng nhập
  - Email verification: user thường phải có email xác minh để đăng bài
  - Thông tin bí mật: private_verification_note chỉ chủ bài thấy
  - Liên hệ ẩn: contact chỉ lộ khi claim được xác minh (≥50 điểm hoặc owner confirm)
  - Ownership check: chỉ chủ bài hoặc admin mới sửa/xóa được
  - Admin audit log: mọi thao tác admin ghi lại với timestamp
  - Debug mode: mặc định tắt (FLASK_DEBUG=false trong .env)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  15. EMAIL & THÔNG BÁO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Gửi bất đồng bộ qua threading — không làm chậm request.
  Tự động bỏ qua nếu chưa cấu hình MAIL_*.

  Sự kiện kích hoạt email:
  ┌────────────────────────────────────┬────────────────────────────────┐
  │ Sự kiện                            │ Nhận email                     │
  ├────────────────────────────────────┼────────────────────────────────┤
  │ Đăng ký mới (có email)             │ User (xác minh) + Admin        │
  │ Thay đổi email                     │ User (xác minh lại email mới)  │
  │ Bài đăng được duyệt                │ Chủ bài                        │
  │ Bài đăng bị từ chối                │ Chủ bài                        │
  │ Có claim khớp (≥50 điểm)           │ Chủ bài nhặt được              │
  │ Có bình luận mới                   │ Chủ bài (preview 50 ký tự)     │
  │ Đăng bài mới chờ duyệt             │ Admin                          │
  │ Admin gửi email hàng loạt          │ Tất cả user hoặc mục tiêu      │
  └────────────────────────────────────┴────────────────────────────────┘

  Thông báo in-app (bảng notifications):
  - Tạo khi có bình luận mới trên bài của user
  - Badge đỏ trên navbar: số lượng thông báo chưa đọc
  - Dropdown hiển thị 10 thông báo gần nhất
  - Đánh dấu đã đọc qua POST /notifications/mark-read


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  16. GÓI VIP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Chỉ áp dụng cho bài mất đồ (post_type = lost).
  Có thể thay đổi giá/ngày/nhãn từ Admin Panel → Cài đặt hệ thống.

  Gói mặc định (cấu hình trong config.py, ghi đè bởi site_settings):

  ┌─────────────┬─────────────┬────────┬────────────┬──────────┬──────┐
  │ Gói         │ Tên         │ Giá    │ Priority   │ Nhãn     │ Ngày │
  ├─────────────┼─────────────┼────────┼────────────┼──────────┼──────┤
  │ Tiêu chuẩn  │ (mặc định)  │ 0đ     │ 0 (thường) │ —        │ —    │
  │ goi_1       │ Nổi bật     │ 10,000 │ 1          │ NỔI BẬT  │ 3    │
  │ goi_2       │ Ưu tiên     │ 20,000 │ 2          │ ƯU TIÊN  │ 5    │
  │ goi_3       │ Tìm gấp     │ 30,000 │ 3          │ TÌM GẤP  │ 10   │
  └─────────────┴─────────────┴────────┴────────────┴──────────┴──────┘

  Luồng thanh toán:
    User chọn gói → tạo lệnh thanh toán (bảng payments, status=pending)
    → User chuyển khoản theo nội dung tự động tạo (LF-{id}-{gói}-{username})
    → User upload ảnh biên lai
    → Admin duyệt (/admin/payments/confirm/<id>) → VIP kích hoạt tức thì
    → Sau hết hạn (vip_expires_at) → cron/mỗi request tự động hạ priority=0

  Mã giảm giá (vouchers):
    Nhập mã tại trang thanh toán → POST /api/voucher/check
    → Giảm % hoặc giảm tiền cố định
    → Áp dụng cho gói cụ thể hoặc tất cả gói
    → Giới hạn lượt sử dụng và thời hạn


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  17. CẤU HÌNH NÂNG CAO (site_settings)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Quản lý tại /admin/settings, lưu trong bảng site_settings.
  Không cần khởi động lại server sau khi thay đổi.

  Nhóm thông tin chung:
    site_name          — Tên hiển thị của site
    site_description   — Mô tả meta
    contact_phone      — Số điện thoại hỗ trợ
    contact_email      — Email hỗ trợ
    contact_address    — Địa chỉ văn phòng

  Nhóm thanh toán:
    bank_name          — Tên ngân hàng (VD: MB Bank)
    bank_account       — Số tài khoản
    bank_owner         — Tên chủ tài khoản

  Nhóm tính năng (toggle on/off):
    feature_vip        — Bật/tắt gói VIP
    feature_ai         — Bật/tắt phân tích AI
    feature_chat       — Bật/tắt chat
    feature_comments   — Bật/tắt bình luận

  Nhóm giới hạn:
    max_posts_per_user     — Giới hạn số bài mỗi user
    max_image_size_mb      — Giới hạn dung lượng ảnh (MB)
    auto_hide_resolved_days — Tự ẩn bài resolved sau N ngày

  Cấu hình gói VIP (ghi đè config.py):
    vip_goi_1_name, vip_goi_1_price, vip_goi_1_days, vip_goi_1_priority, vip_goi_1_label
    vip_goi_2_name, vip_goi_2_price, vip_goi_2_days, vip_goi_2_priority, vip_goi_2_label
    vip_goi_3_name, vip_goi_3_price, vip_goi_3_days, vip_goi_3_priority, vip_goi_3_label


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  18. CHANGELOG — v2.0 MODULAR (2026-04-18 → 2026-04-19)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  So với phiên bản 1.0 monolithic (app_legacy.py):

  [KIẾN TRÚC]
  + Tách app.py đơn file 3800+ dòng thành 10 blueprint module
    (auth, home, profile, posts, search, claims, chat, payment, api, admin)
  + app.py chỉ còn ~200 dòng — thin entry point
  + Mỗi file blueprint có docstring mô tả các route bên trong

  [TÍNH NĂNG MỚI]
  + Hồ sơ cá nhân nâng cao:
    - Upload ảnh đại diện (Pillow resize 300×300, lưu avatars/)
    - Tab Thông tin: cập nhật họ tên, email, bio (AJAX, không reload)
    - Tab Bảo mật: đổi mật khẩu với strength meter
    - Gửi lại email xác minh từ profile
  + Xác minh email bắt buộc trước khi đăng bài
    (admin/moderator được miễn)
  + Hệ thống thông báo in-app (bảng notifications + badge)
  + Chat SSE (Server-Sent Events) realtime
  + Avatar trong base_dashboard.html dùng ảnh đã upload thay vì external URL
  + Layout dashboard dạng sidebar cho trang tạo bài (base_dashboard.html)

  [BẢO MẬT]
  + Flask-WTF CSRFProtect — bảo vệ tất cả POST form
  + flask-session (filesystem, signed) thay cookie session
  + CSRF auto-inject JS cho cả base.html, base_admin.html, base_dashboard.html
  + X-CSRFToken header tự động đính vào mọi fetch() POST

  [BUG FIX]
  + base_dashboard.html thiếu CSRF meta tag → fetch /api/analyze-image bị 400
  + Admin/moderator bị redirect khi truy cập /create do không có email xác minh
  + Connection leak trong route edit_post (dùng lại conn thay vì tạo mới)

  [PHỤ THUỘC MỚI]
    flask-session>=0.8.0   — session lưu filesystem
    flask-wtf>=1.2.0       — CSRF protection
    Pillow>=10.0.0         — xử lý ảnh


================================================================================
  ĐƯỢC PHÁT TRIỂN VÀ REVIEW BỞI: Claude Sonnet 4.6 — 2026-04-19
================================================================================
