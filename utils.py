import os
import time
import json
import hashlib
import tempfile
from functools import wraps
from flask import request, jsonify, flash, redirect, url_for

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

    Uses file-based storage so limits are shared across gunicorn workers.
    Falls back to in-memory if file writes fail.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            key = f"{key_prefix}:{request.remote_addr if use_ip else 'global'}"
            now = time.time()
            window_start = now - window

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
