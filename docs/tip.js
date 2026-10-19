document.querySelectorAll('.tipfig').forEach(fig => {
  const tip = fig.querySelector('.tip');
  fig.querySelectorAll('[data-tip]').forEach(el => {
    const show = () => {
      tip.textContent = el.dataset.tip;
      const f = fig.getBoundingClientRect(), b = el.getBoundingClientRect();
      tip.style.left = Math.min(b.left - f.left, f.width - 300) + 'px';
      tip.style.top = (b.bottom - f.top + 8) + 'px';
      tip.classList.add('on');
    };
    const hide = () => tip.classList.remove('on');
    el.addEventListener('mouseenter', show); el.addEventListener('focus', show);
    el.addEventListener('mouseleave', hide); el.addEventListener('blur', hide);
  });
});
