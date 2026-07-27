import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    PLATFORM_FEE_PERCENT = 0.10
    PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY')
    PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY')

    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')

    RESEND_API_KEY = os.environ.get('RESEND_API_KEY')

    APP_URL = os.environ.get('APP_URL') or os.environ.get('RENDER_EXTERNAL_URL', 'http://127.0.0.1:5000')

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)

    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

    @staticmethod
    def validate(production=False):
        fatal = []
        warnings = []
        if not Config.SECRET_KEY or Config.SECRET_KEY == 'change-me-in-production':
            fatal.append('SECRET_KEY is not set. Generate one: python3 -c "import secrets; print(secrets.token_hex(32))"')
        if production:
            db_url = os.environ.get('DATABASE_URL', '').strip()
            if not db_url:
                fatal.append('DATABASE_URL is not set')
        if not Config.PAYSTACK_SECRET_KEY or not Config.PAYSTACK_PUBLIC_KEY:
            warnings.append('PAYSTACK_SECRET_KEY and PAYSTACK_PUBLIC_KEY not set — payments will fail')
        if not Config.RESEND_API_KEY:
            warnings.append('RESEND_API_KEY not set — email notifications will fail silently')
        import sys
        if fatal:
            print("FATAL CONFIGURATION ERRORS:", file=sys.stderr)
            for err in fatal:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)
        return warnings


class DevelopmentConfig(Config):
    DEBUG = True
    _dev_url = os.environ.get('DATABASE_URL') or 'sqlite:///campus_plug.db'
    SQLALCHEMY_DATABASE_URI = _dev_url
    if _dev_url.startswith('postgresql://') or _dev_url.startswith('postgres://'):
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_size': 10,
            'max_overflow': 20,
            'pool_pre_ping': True,
            'pool_recycle': 300,
        }
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = True

    CONTENT_SECURITY_POLICY = {
        'default-src': "'self'",
        'script-src': "'self' 'unsafe-inline' https://cdn.jsdelivr.net https://js.paystack.co https://unpkg.com",
        'style-src': "'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com",
        'img-src': "'self' data: blob: https:",
        'font-src': "'self' https://fonts.gstatic.com",
        'connect-src': "'self' https://api.paystack.co https://nominatim.openstreetmap.org https://router.project-osrm.org",
        'frame-src': "'self' https://js.paystack.co",
        'object-src': "'none'",
        'base-uri': "'self'",
    }


class ProductionConfig(Config):
    DEBUG = False
    _db_url = (os.environ.get('DATABASE_URL') or '').strip()
    _normalized_url = _db_url.replace('postgres://', 'postgresql://', 1) if _db_url else ''
    SQLALCHEMY_DATABASE_URI = _normalized_url
    if _normalized_url.startswith('postgresql://'):
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_size': 20,
            'max_overflow': 40,
            'pool_pre_ping': True,
            'pool_recycle': 300,
            'pool_use_lifo': True,
        }
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_ENABLED = True

    CONTENT_SECURITY_POLICY = {
        'default-src': "'self'",
        'script-src': "'self' 'unsafe-inline' https://cdn.jsdelivr.net https://js.paystack.co https://unpkg.com",
        'style-src': "'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com",
        'img-src': "'self' data: blob: https:",
        'font-src': "'self' https://fonts.gstatic.com",
        'connect-src': "'self' https://api.paystack.co https://nominatim.openstreetmap.org https://router.project-osrm.org",
        'frame-src': "'self' https://js.paystack.co",
        'object-src': "'none'",
        'base-uri': "'self'",
    }
