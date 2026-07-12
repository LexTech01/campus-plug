import os
import time
import json
import hashlib
import logging
from functools import wraps
from datetime import datetime, timedelta
import bleach
from flask import request, jsonify, flash, redirect, url_for, current_app
from flask_login import current_user

logger = logging.getLogger(__name__)

_redis_client = None

def get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            url = os.environ.get('REDIS_URL') or current_app.config.get('REDIS_URL', '')
            if url:
                _redis_client = redis.from_url(url, decode_responses=True)
                _redis_client.ping()
        except Exception as e:
            logger.warning(f"Redis unavailable: {e}. Rate limiting disabled — consider setting REDIS_URL in production.")
            _redis_client = False
    return _redis_client if _redis_client else None

def rate_limit(key_prefix, max_attempts=5, window=60, use_ip=True):
    """Decorator: limit requests per IP (or custom key) within a time window.

    Requires Redis. Logs warning and bypasses if Redis is unavailable.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            key = f"{key_prefix}:{request.remote_addr if use_ip else 'global'}"
            now = time.time()
            window_start = now - window

            r = get_redis()
            if not r:
                current_app.logger.warning(f"Rate limit bypassed for {key_prefix} — no Redis connection")
                return f(*args, **kwargs)

            pipe = r.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            count = pipe.execute()[1]
            if count >= max_attempts:
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': f'Too many attempts. Try again in {window // 60} minute(s).'}), 429
                flash(f"Too many attempts. Try again in {window // 60} minute(s).", "warning")
                return redirect(request.referrer or url_for('index'))
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, window)
            pipe.execute()
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── Caching ───────────────────────────────────────────────────────────

def cache_get(key):
    r = get_redis()
    if not r:
        return None
    try:
        val = r.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None

def cache_set(key, value, ttl=30):
    r = get_redis()
    if not r:
        return
    try:
        r.setex(key, ttl, json.dumps(value))
    except Exception:
        pass

def cache_delete(key):
    r = get_redis()
    if not r:
        return
    try:
        r.delete(key)
    except Exception:
        pass

def cache_delete_pattern(pattern):
    r = get_redis()
    if not r:
        return
    try:
        for k in r.scan_iter(match=pattern):
            r.delete(k)
    except Exception:
        pass

def memoize(ttl=30):
    """Decorator: cache function result in Redis with given TTL."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            key_parts = [f.__name__] + [str(a) for a in args] + [f'{k}={v}' for k, v in sorted(kwargs.items())]
            key = f"cache:{hashlib.md5(':'.join(key_parts).encode()).hexdigest()}"
            cached = cache_get(key)
            if cached is not None:
                return cached
            result = f(*args, **kwargs)
            cache_set(key, result, ttl)
            return result
        return wrapper
    return decorator


_ALLOWED_TAGS = {'b', 'i', 'u', 'em', 'strong', 'a', 'br', 'p', 'ul', 'ol', 'li', 'span'}
_ALLOWED_ATTRS = {'a': ['href', 'title', 'rel'], 'span': ['class']}

def sanitize_html(text, strip=True):
    if not text:
        return text
    return bleach.clean(text, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=strip)

def sanitize_plain_text(text):
    if not text:
        return text
    return bleach.clean(text, tags=[], attributes={}, strip=True)


def check_account_age(min_hours=24):
    if not current_user.is_authenticated:
        return True
    age = datetime.utcnow() - current_user.created_at
    return age.total_seconds() < min_hours * 3600
