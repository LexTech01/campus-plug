document.addEventListener('DOMContentLoaded', function () {
  if (typeof lucide !== 'undefined') lucide.createIcons();

  setInterval(function () {
    fetch('/auth/heartbeat', { method: 'POST', cache: 'no-store' }).catch(function () {});
  }, 120000);
});

(function () {
  var tokenMeta = document.querySelector('meta[name="csrf-token"]');
  if (!tokenMeta) return;
  var csrfToken = tokenMeta.getAttribute('content');

  var originalFetch = window.fetch;
  window.fetch = function (url, options) {
    options = options || {};
    if (options.method && options.method.toUpperCase() !== 'GET') {
      options.headers = options.headers || {};
      options.headers['X-CSRFToken'] = csrfToken;
    }
    return originalFetch.call(this, url, options);
  };

  if (typeof XMLHttpRequest !== 'undefined') {
    var origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method) {
      this._method = method;
      return origOpen.apply(this, arguments);
    };
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function (body) {
      if (this._method && this._method.toUpperCase() !== 'GET') {
        this.setRequestHeader('X-CSRFToken', csrfToken);
      }
      return origSend.apply(this, arguments);
    };
  }
})();
