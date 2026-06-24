document.addEventListener('DOMContentLoaded', () => {
  const header = document.getElementById('main-header');
  let scrollY = window.scrollY;

  // ── Sticky header ──
  if (header) {
    window.addEventListener('scroll', () => {
      scrollY = window.scrollY;
      header.classList.toggle('header-scrolled', scrollY > 80);
    }, { passive: true });
  }

  // ── Mobile hamburger with slide animation ──
  const menuBtn = document.getElementById('menu-btn');
  const mobileMenu = document.getElementById('mobile-menu');
  const mobileBackdrop = document.getElementById('mobile-backdrop');
  const iconOpen = document.getElementById('menu-icon-open');
  const iconClose = document.getElementById('menu-icon-close');

  function openMenu() {
    mobileMenu.classList.remove('translate-x-full');
    mobileMenu.classList.add('translate-x-0');
    mobileBackdrop.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    iconOpen.classList.add('hidden');
    iconClose.classList.remove('hidden');
    menuBtn.setAttribute('aria-expanded', 'true');
  }

  function closeMenu() {
    mobileMenu.classList.remove('translate-x-0');
    mobileMenu.classList.add('translate-x-full');
    mobileBackdrop.classList.add('hidden');
    document.body.style.overflow = '';
    iconOpen.classList.remove('hidden');
    iconClose.classList.add('hidden');
    menuBtn.setAttribute('aria-expanded', 'false');
  }

  window.closeMobileMenu = closeMenu;

  if (menuBtn && mobileMenu && mobileBackdrop) {
    menuBtn.addEventListener('click', () => {
      if (mobileMenu.classList.contains('translate-x-0')) {
        closeMenu();
      } else {
        openMenu();
      }
    });

    mobileBackdrop.addEventListener('click', closeMenu);

    // Close menu on resize to desktop
    window.addEventListener('resize', () => {
      if (window.innerWidth >= 768 && mobileMenu.classList.contains('translate-x-0')) {
        closeMenu();
      }
    });
  }

  // ── Scroll-triggered AOS animations ──
  const aosElements = document.querySelectorAll('[data-aos]');
  if (!aosElements.length) return;

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('aos-visible');
        observer.unobserve(entry.target);
      }
    });
  }, {
    threshold: 0.08,
    rootMargin: '0px 0px -40px 0px',
  });

  aosElements.forEach((el) => observer.observe(el));
});