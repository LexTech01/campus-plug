document.addEventListener('DOMContentLoaded', () => {
  const isDark = document.documentElement.classList.contains('dark');

  document.querySelectorAll('#theme-toggle').forEach((btn) => {
    const sunIcon = btn.querySelector('#theme-sun');
    const moonIcon = btn.querySelector('#theme-moon');

    const updateIcons = (dark) => {
      if (sunIcon) sunIcon.classList.toggle('hidden', !dark);
      if (moonIcon) moonIcon.classList.toggle('hidden', dark);
    };

    updateIcons(isDark);

    btn.addEventListener('click', () => {
      const nowDark = document.documentElement.classList.toggle('dark');
      localStorage.setItem('theme', nowDark ? 'dark' : 'light');
      updateIcons(nowDark);
    });
  });
});
