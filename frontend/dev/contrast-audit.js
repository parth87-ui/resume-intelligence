/**
 * WCAG contrast audit for the dashboard.
 *
 * Paste this whole file into the browser console on any page of the running
 * app, then:
 *
 *     await contrastAudit.run()          // audit the current theme, all pages
 *     await contrastAudit.runBothThemes() // audit light and dark
 *     contrastAudit.page()               // audit just what is on screen now
 *
 * Why this exists: the palette is defined once as design tokens, but whether a
 * token *pair* is readable depends on what it lands on - a chip tint over a
 * card gradient over the page wash. That composite is only knowable at runtime,
 * so this walks the real DOM, composites every translucent ancestor, and
 * reports anything under WCAG AA (4.5:1 for body text, 3:1 for large text).
 *
 * Elements sitting on a CSS gradient (the brand mark, the primary button) are
 * skipped: their effective background cannot be read from `backgroundColor`,
 * and reporting them produces false failures.
 */

(function () {
  const parseColor = (value) => {
    const match = value.match(/rgba?\(([^)]+)\)/);
    if (!match) return null;
    const parts = match[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };

  const composite = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1,
  });

  const luminance = (c) => {
    const channel = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
  };

  const contrast = (a, b) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };

  const sitsOnGradient = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const style = getComputedStyle(node);
      if (style.backgroundImage && /gradient/.test(style.backgroundImage)) return true;
      const bg = parseColor(style.backgroundColor);
      if (bg && bg.a === 1) return false;
      node = node.parentElement;
    }
    return false;
  };

  /** Effective background: composite each translucent ancestor onto the page. */
  const backgroundOf = (el) => {
    const layers = [];
    let node = el;
    while (node && node !== document.documentElement) {
      const bg = parseColor(getComputedStyle(node).backgroundColor);
      if (bg && bg.a > 0) {
        layers.push(bg);
        if (bg.a === 1) break;
      }
      node = node.parentElement;
    }
    let base = parseColor(getComputedStyle(document.body).backgroundColor)
      || { r: 255, g: 255, b: 255, a: 1 };
    for (let i = layers.length - 1; i >= 0; i -= 1) base = composite(layers[i], base);
    return base;
  };

  function page() {
    const failures = [];
    const seen = new Set();

    document.querySelectorAll('.main *, .sidebar *').forEach((el) => {
      const text = [...el.childNodes]
        .filter((n) => n.nodeType === Node.TEXT_NODE)
        .map((n) => n.textContent.trim())
        .join('');
      if (!text || text.length < 2) return;

      const style = getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none') return;
      if (parseFloat(style.opacity) < 0.3) return;
      const rect = el.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      if (sitsOnGradient(el)) return;

      const fg = parseColor(style.color);
      if (!fg) return;
      const bg = backgroundOf(el);
      const ratio = contrast(composite(fg, bg), bg);

      const size = parseFloat(style.fontSize);
      const bold = parseInt(style.fontWeight, 10) >= 700;
      const isLarge = size >= 24 || (size >= 18.66 && bold);
      const required = isLarge ? 3.0 : 4.5;

      if (ratio < required) {
        const key = `${style.color}|${el.className}|${size}`;
        if (seen.has(key)) return;
        seen.add(key);
        failures.push({
          ratio: Number(ratio.toFixed(2)),
          required,
          fontSize: Number(size.toFixed(1)),
          selector: (el.className || el.tagName).toString().slice(0, 40),
          color: style.color,
          sample: text.slice(0, 40),
        });
      }
    });

    return failures.sort((a, b) => a.ratio - b.ratio);
  }

  const ROUTES = ['home', 'upload', 'target', 'dashboard', 'gaps', 'projects', 'roadmap'];
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function run() {
    const results = [];
    const startedAt = location.hash;
    for (const route of ROUTES) {
      location.hash = `#/${route}`;
      await wait(650);
      results.push(...page().map((failure) => ({ route, ...failure })));
    }
    location.hash = startedAt || '#/home';
    const theme = document.documentElement.getAttribute('data-theme') || 'light';
    if (results.length) {
      console.warn(`${results.length} contrast failure(s) in the ${theme} theme`);
      console.table(results);
    } else {
      console.log(`%c✓ ${theme} theme passes WCAG AA on all ${ROUTES.length} pages`,
        'color:#16a34a;font-weight:600');
    }
    return results;
  }

  async function runBothThemes() {
    const button = document.getElementById('theme-btn');
    const first = await run();
    if (!button) {
      console.warn('No theme toggle found - audited the current theme only.');
      return { current: first };
    }
    button.click();
    await wait(600);
    const second = await run();
    button.click();
    return { first, second };
  }

  window.contrastAudit = { page, run, runBothThemes };
  console.log('contrastAudit ready — try: await contrastAudit.runBothThemes()');
})();
