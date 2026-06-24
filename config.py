import os
import re

def _load_env():
    paths = ['.env']
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, val = line.split('=', 1)
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = val

_load_env()


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

    APP_URL = os.environ.get('APP_URL', 'http://127.0.0.1:5000')

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    @staticmethod
    def validate(production=False):
        errors = []
        if not Config.SECRET_KEY or Config.SECRET_KEY == 'change-me-in-production':
            errors.append('SECRET_KEY is not set. Generate one: python3 -c "import secrets; print(secrets.token_hex(32))"')
        if not Config.PAYSTACK_SECRET_KEY or not Config.PAYSTACK_PUBLIC_KEY:
            errors.append('PAYSTACK_SECRET_KEY and PAYSTACK_PUBLIC_KEY must be set in .env')
        if production:
            import sys
            if errors:
                print("CRITICAL CONFIGURATION ERRORS:", file=sys.stderr)
                for err in errors:
                    print(f"  - {err}", file=sys.stderr)
                sys.exit(1)
        return errors


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///campus_plug.db'
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = True


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', '').replace('postgres://', 'postgresql://', 1) if os.environ.get('DATABASE_URL') else ''
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_ENABLED = True

    CONTENT_SECURITY_POLICY = {
        'default-src': "'self'",
        'script-src': "'self' https://cdn.jsdelivr.net https://js.paystack.co 'unsafe-inline'",
        'style-src': "'self' https://cdn.tailwindcss.com https://fonts.googleapis.com 'unsafe-inline'",
        'img-src': "'self' data: https:",
        'font-src': "'self' https://fonts.gstatic.com",
        'connect-src': "'self' https://api.paystack.co https://nominatim.openstreetmap.org https://router.project-osrm.org",
        'frame-src': "'self' https://js.paystack.co",
        'object-src': "'none'",
        'base-uri': "'self'",
    }
