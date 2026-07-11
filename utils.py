import os
import time
import json
import hashlib
import tempfile
from functools import wraps
import bleach
from flask import request, jsonify, flash, redirect, url_for, current_app

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
        except Exception:
            _redis_client = False
    return _redis_client if _redis_client else None

# ── File-based fallback (shared across gunicorn workers) ──
_RATE_LIMIT_DIR = os.environ.get('RATE_LIMIT_DIR') or os.path.join(tempfile.gettempdir(), 'campus_plug_ratelimit')

def _get_rate_file(key):
    h = hashlib.md5(key.encode('utf-8')).hexdigest()
    return os.path.join(_RATE_LIMIT_DIR, h)

def _read_timestamps(key):
    path = _get_rate_file(key)
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

def _write_timestamps(key, timestamps):
    os.makedirs(_RATE_LIMIT_DIR, exist_ok=True)
    path = _get_rate_file(key)
    try:
        with open(path, 'w') as f:
            json.dump(timestamps, f)
    except OSError:
        pass

def _clean_timestamps(timestamps, window_start):
    return [t for t in timestamps if t > window_start]

# ── In-memory fallback (per-process, used when file writes fail) ──
_in_memory_limits = {}

def rate_limit(key_prefix, max_attempts=5, window=60, use_ip=True):
    """Decorator: limit requests per IP (or custom key) within a time window.

    Uses Redis when available, falls back to file-based, then in-memory.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            key = f"{key_prefix}:{request.remote_addr if use_ip else 'global'}"
            now = time.time()
            window_start = now - window

            r = get_redis()
            if r:
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

            timestamps = _read_timestamps(key)
            if not timestamps:
                timestamps = _in_memory_limits.get(key, [])

            timestamps = _clean_timestamps(timestamps, window_start)

            if len(timestamps) >= max_attempts:
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': f'Too many attempts. Try again in {window // 60} minute(s).'}), 429
                flash(f"Too many attempts. Try again in {window // 60} minute(s).", "warning")
                return redirect(request.referrer or url_for('index'))

            timestamps.append(now)
            _write_timestamps(key, timestamps)
            _in_memory_limits[key] = timestamps
            return f(*args, **kwargs)
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
