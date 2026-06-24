document.addEventListener('DOMContentLoaded', () => {
  const toastContainer = document.getElementById('toast-container');
  if (toastContainer) {
    const toasts = toastContainer.querySelectorAll('.toast-alert');
    
    toasts.forEach(toast => {
      // Set timer to start exit transition after 4.5s
      setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-x-12');
        // Fully remove from DOM after CSS transition finishes
        setTimeout(() => {
          toast.remove();
        }, 300);
      }, 4500);

      // Support close button clicking
      const closeBtn = toast.querySelector('.toast-close-btn');
      if (closeBtn) {
        closeBtn.addEventListener('click', () => {
          toast.classList.add('opacity-0', 'translate-x-12');
          setTimeout(() => {
            toast.remove();
          }, 300);
        });
      }
    });
  }
});
