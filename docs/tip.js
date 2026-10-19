// Hover a box in a figure: its file (first lines, monospace), then what it is.
document.querySelectorAll('.tipfig').forEach(fig => {
  const tip = fig.querySelector('.tip');
  fig.querySelectorAll('[data-tip]').forEach(el => {
    const show = () => {
      const lines = el.dataset.tip.split('\n');
      const text = lines.pop();
      tip.replaceChildren(
        ...lines.map(l => Object.assign(document.createElement('code'), { textContent: l })),
        Object.assign(document.createElement('span'), { textContent: text }),
      );
      const f = fig.getBoundingClientRect(), b = el.getBoundingClientRect();
      tip.style.left = Math.max(0, Math.min(b.left - f.left, f.width - 320)) + 'px';
      tip.style.top = (b.bottom - f.top + 8) + 'px';
      tip.classList.add('on');
    };
    const hide = () => tip.classList.remove('on');
    el.addEventListener('mouseenter', show); el.addEventListener('focus', show);
    el.addEventListener('mouseleave', hide); el.addEventListener('blur', hide);
  });
});
