import time
from functools import wraps
from flask import request, jsonify, flash, redirect, url_for

# Simple in-memory rate limiter
_rate_limits = {}

def rate_limit(key_prefix, max_attempts=5, window=60, use_ip=True):
    """Decorator: limit requests per IP (or custom key) within a time window."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            key = f"{key_prefix}:{request.remote_addr if use_ip else 'global'}"
            now = time.time()
            window_start = now - window
            # Clean old entries
            if key in _rate_limits:
                _rate_limits[key] = [t for t in _rate_limits[key] if t > window_start]
            else:
                _rate_limits[key] = []
            if len(_rate_limits[key]) >= max_attempts:
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': f'Too many attempts. Try again in {window // 60} minute(s).'}), 429
                flash(f"Too many attempts. Try again in {window // 60} minute(s).", "warning")
                return redirect(request.referrer or url_for('index'))
            _rate_limits[key].append(now)
            return f(*args, **kwargs)
        return wrapper
    return decorator
