function syncHeroHeaderHeight() {
  var header = document.getElementById('main-header');
  if (!header) return;
  var height = header.getBoundingClientRect().height;
  document.documentElement.style.setProperty('--hero-header-height', height + 'px');
}

document.addEventListener('DOMContentLoaded', function () {
  if (typeof lucide !== 'undefined') lucide.createIcons();

  syncHeroHeaderHeight();
  window.addEventListener('resize', syncHeroHeaderHeight);

  setInterval(function () {
    fetch('/auth/heartbeat', { method: 'POST', cache: 'no-store' }).catch(function () {});
  }, 120000);

  var passwordToggleButtons = document.querySelectorAll('.password-toggle');
  passwordToggleButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      var fieldWrapper = button.closest('.password-field');
      if (!fieldWrapper) return;
      var input = fieldWrapper.querySelector('input[type="password"], input[type="text"]');
      if (!input) return;

      var isPassword = input.type === 'password';
      input.type = isPassword ? 'text' : 'password';
      button.setAttribute('aria-label', isPassword ? 'Hide password' : 'Show password');
      button.dataset.visible = isPassword ? 'true' : 'false';
      var icon = button.querySelector('i');
      if (icon) {
        icon.dataset.lucide = isPassword ? 'eye-off' : 'eye';
        if (typeof lucide !== 'undefined') {
          lucide.replace();
        }
      }
    });
  });
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
