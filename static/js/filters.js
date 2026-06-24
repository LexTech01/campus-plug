document.addEventListener('DOMContentLoaded', () => {
  // 1. Hover-to-preview image carousels on listing cards
  const productCards = document.querySelectorAll('.listing-card');
  productCards.forEach(card => {
    const mainImg = card.querySelector('.listing-card-img');
    if (!mainImg) return;
    
    const photosData = card.getAttribute('data-photos');
    if (!photosData) return;
    
    const photos = photosData.split(',').map(p => p.trim()).filter(p => p !== '');
    if (photos.length <= 1) return; // Only trigger if multiple pictures exist
    
    let originalSrc = mainImg.src;
    let hoverInterval = null;
    let photoIndex = 0;
    
    card.addEventListener('mouseenter', () => {
      // Rotate through images every 1.5 seconds on hover
      hoverInterval = setInterval(() => {
        photoIndex = (photoIndex + 1) % photos.length;
        mainImg.src = photos[photoIndex];
      }, 1500);
    });
    
    card.addEventListener('mouseleave', () => {
      if (hoverInterval) {
        clearInterval(hoverInterval);
      }
      mainImg.src = originalSrc; // Reset to prime image
      photoIndex = 0;
    });
  });

  // 2. Clear filters helper
  const clearFiltersBtn = document.getElementById('clear-filters');
  if (clearFiltersBtn) {
    clearFiltersBtn.addEventListener('click', (e) => {
      e.preventDefault();
      const form = clearFiltersBtn.closest('form');
      if (form) {
        // Reset all selects, inputs, and textfields
        form.querySelectorAll('select').forEach(sel => sel.selectedIndex = 0);
        form.querySelectorAll('input[type="text"]').forEach(inp => inp.value = '');
        form.querySelectorAll('input[type="number"]').forEach(inp => inp.value = '');
        
        // Go back to default search path
        const basePath = window.location.pathname;
        window.location.href = basePath;
      }
    });
  }

  // 3. Shaking invalid input fields on forms (for signups/logins)
  const formToValidate = document.querySelector('.validate-shake-form');
  if (formToValidate) {
    formToValidate.addEventListener('submit', (e) => {
      let isFormValid = true;
      const requiredInputs = formToValidate.querySelectorAll('input[required], select[required]');
      
      requiredInputs.forEach(input => {
        if (!input.value.trim()) {
          isFormValid = false;
          input.classList.add('shake-error');
          
          // Remove shake class after animation completes
          setTimeout(() => {
            input.classList.remove('shake-error');
          }, 500);
        }
      });
      
      if (!isFormValid) {
        e.preventDefault(); // Stop submission if empty required fields
      }
    });
  }

  // 4. Jumia-style filter sidebar: show-more toggles
  document.querySelectorAll('[data-filter-expand]').forEach(button => {
    const container = button.closest('.filter-group-content');
    if (!container) return;

    const hiddenItems = container.querySelectorAll('.filter-option-hidden');
    if (hiddenItems.length === 0) return;

    const selectedHidden = Array.from(hiddenItems).some(item =>
      item.querySelector('input[type="radio"]')?.checked
    );
    if (selectedHidden) {
      container.classList.add('is-expanded');
      button.textContent = button.dataset.lessLabel || 'Show less';
    }

    button.addEventListener('click', () => {
      const expanded = container.classList.toggle('is-expanded');
      button.textContent = expanded
        ? (button.dataset.lessLabel || 'Show less')
        : (button.dataset.moreLabel || 'Show more');
    });
  });

  // 5. Auto-submit sidebar filters on change
  document.querySelectorAll('.filter-submit-input').forEach(element => {
    element.addEventListener('change', () => {
      element.closest('form')?.submit();
    });
  });
});
