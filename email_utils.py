import os
import threading
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(to_email, subject, html_body):
    """Gửi email bất đồng bộ. Bỏ qua nếu chưa cấu hình MAIL_USERNAME."""
    if not to_email:
        return
    mail_user = os.environ.get("MAIL_USERNAME", "").strip()
    mail_pass = os.environ.get("MAIL_PASSWORD", "").strip()
    if not mail_user or not mail_pass:
        return

    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = os.environ.get("MAIL_FROM", mail_user)
            msg["To"] = to_email
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            server = smtplib.SMTP(
                os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
                int(os.environ.get("MAIL_PORT", 587))
            )
            server.starttls()
            server.login(mail_user, mail_pass)
            server.sendmail(mail_user, to_email, msg.as_string())
            server.quit()
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()
