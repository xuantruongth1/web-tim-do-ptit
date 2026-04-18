"""Flask extensions — khởi tạo không gắn app, dùng init_app() trong create_app()."""
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(key_func=get_remote_address, default_limits=[])
    HAS_LIMITER = True
except ImportError:
    limiter = None
    HAS_LIMITER = False

try:
    from flask_session import Session
    flask_session = Session()
    HAS_FLASK_SESSION = True
except ImportError:
    flask_session = None
    HAS_FLASK_SESSION = False

try:
    from flask_wtf.csrf import CSRFProtect, generate_csrf
    csrf = CSRFProtect()
    HAS_CSRF = True
except ImportError:
    csrf = None
    generate_csrf = lambda: ""
    HAS_CSRF = False


def rate(limit_string):
    """Decorator wrapper cho rate limiting; no-op nếu flask-limiter chưa cài."""
    if HAS_LIMITER and limiter:
        return limiter.limit(limit_string)
    def _noop(f):
        return f
    return _noop
