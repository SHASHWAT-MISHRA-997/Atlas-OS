// Applies the saved theme before the page paints, so it never flashes the wrong colours.
try { const t = localStorage.getItem('atlas.theme'); if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; } catch { /* storage off */ }
