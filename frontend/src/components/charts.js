/**
 * Interactive SVG charts — gauge, donut, radar, bars and progress meters.
 *
 * These are hand-built rather than pulled from a charting CDN so the dashboard
 * renders identically offline, matches the design tokens exactly, and adds no
 * download to the page. Each function returns an SVG string; hover interaction
 * is attached by `activateChartTooltips()` after insertion.
 */

import { esc, scoreColor } from './ui.js';

const TAU = Math.PI * 2;

function polar(cx, cy, radius, angleDeg) {
  const a = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + radius * Math.cos(a), y: cy + radius * Math.sin(a) };
}

function arcPath(cx, cy, radius, startDeg, endDeg) {
  const start = polar(cx, cy, radius, endDeg);
  const end = polar(cx, cy, radius, startDeg);
  const large = endDeg - startDeg <= 180 ? 0 : 1;
  return `M ${start.x.toFixed(2)} ${start.y.toFixed(2)} A ${radius} ${radius} 0 ${large} 0 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`;
}

/** Big animated score gauge (270° sweep). */
export function gauge(value, { size = 232, band = '', label = 'Match score' } = {}) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 20;
  const sweep = 270;
  const startAngle = -135;
  const clamped = Math.max(0, Math.min(100, value));
  const endAngle = startAngle + (sweep * clamped) / 100;
  const colour = scoreColor(clamped);
  const circumference = (sweep / 360) * TAU * r;
  const filled = (clamped / 100) * circumference;
  const ticks = [40, 55, 70, 85]
    .map((t) => {
      const a = startAngle + (sweep * t) / 100;
      const outer = polar(cx, cy, r + 8, a);
      const inner = polar(cx, cy, r + 3, a);
      return `<line x1="${inner.x}" y1="${inner.y}" x2="${outer.x}" y2="${outer.y}" stroke="var(--tick)" stroke-width="1.5"/>`;
    })
    .join('');

  return `
  <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img"
       aria-label="${esc(label)}: ${clamped.toFixed(0)} out of 100${band ? `, ${esc(band)}` : ''}">
    <defs>
      <linearGradient id="gaugeGrad" x1="0" y1="1" x2="1" y2="0">
        <stop offset="0%" stop-color="${colour}" stop-opacity="0.55"/>
        <stop offset="100%" stop-color="${colour}"/>
      </linearGradient>
      <filter id="gaugeGlow" x="-40%" y="-40%" width="180%" height="180%">
        <feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
    </defs>
    <path d="${arcPath(cx, cy, r, startAngle, startAngle + sweep)}" fill="none"
          stroke="var(--track)" stroke-width="13" stroke-linecap="round"/>
    ${ticks}
    <path d="${arcPath(cx, cy, r, startAngle, endAngle)}" fill="none" stroke="url(#gaugeGrad)"
          stroke-width="13" stroke-linecap="round" filter="url(#gaugeGlow)"
          stroke-dasharray="${filled.toFixed(1)} ${(circumference * 2).toFixed(1)}"
          style="animation: gaugeDraw 1.2s cubic-bezier(.22,1,.36,1) both">
      <animate attributeName="stroke-dashoffset" from="${filled.toFixed(1)}" to="0" dur="1.2s" fill="freeze"/>
    </path>
    <text x="${cx}" y="${cy - 2}" text-anchor="middle" font-size="46" font-weight="680"
          fill="var(--text)" data-countup="${clamped}" style="font-variant-numeric:tabular-nums">0</text>
    <text x="${cx}" y="${cy + 24}" text-anchor="middle" font-size="12.5" fill="var(--text-faint)"
          letter-spacing="1.4">OUT OF 100</text>
  </svg>`;
}

/** Donut chart with a centred total. */
export function donut(labels, values, colors, { size = 210, centreLabel = '' } = {}) {
  const total = values.reduce((a, b) => a + b, 0);
  if (!total) return `<p class="small faint center">No data to chart.</p>`;
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 12;
  const inner = r * 0.62;
  let angle = 0;
  const slices = values
    .map((value, i) => {
      if (!value) return '';
      const share = value / total;
      const start = angle;
      const end = angle + share * 360;
      angle = end;
      const p1 = polar(cx, cy, r, start);
      const p2 = polar(cx, cy, r, end);
      const p3 = polar(cx, cy, inner, end);
      const p4 = polar(cx, cy, inner, start);
      const large = end - start > 180 ? 1 : 0;
      const d = [
        `M ${p1.x} ${p1.y}`,
        `A ${r} ${r} 0 ${large} 1 ${p2.x} ${p2.y}`,
        `L ${p3.x} ${p3.y}`,
        `A ${inner} ${inner} 0 ${large} 0 ${p4.x} ${p4.y}`,
        'Z',
      ].join(' ');
      const pct = ((share * 100).toFixed(0));
      return `<path d="${d}" fill="${colors[i]}" opacity="0.88" class="slice"
                data-tip="${esc(labels[i])}: ${value} (${pct}%)"
                style="transition:opacity .18s, transform .18s; transform-origin:${cx}px ${cy}px"/>`;
    })
    .join('');

  return `
  <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img"
       aria-label="${esc(labels.map((l, i) => `${l}: ${values[i]}`).join(', '))}">
    ${slices}
    <text x="${cx}" y="${cy - 4}" text-anchor="middle" font-size="27" font-weight="660" fill="var(--text)">${total}</text>
    <text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="10.5" fill="var(--text-faint)"
          letter-spacing="1.1">${esc(centreLabel.toUpperCase())}</text>
  </svg>`;
}

export function legend(labels, colors, values) {
  return `<div class="legend">${labels
    .map(
      (label, i) =>
        `<div class="item"><span class="swatch" style="background:${colors[i]}"></span>${esc(label)}${
          values ? ` <strong style="color:var(--text)">${values[i]}</strong>` : ''
        }</div>`
    )
    .join('')}</div>`;
}

/** Radar chart: candidate coverage vs the target's 100% requirement line. */
export function radar(axes, { size = 320 } = {}) {
  if (!axes || axes.length < 3) {
    return `<p class="small faint center">Radar needs at least three skill categories in the target profile.</p>`;
  }
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 54;
  const step = 360 / axes.length;

  const rings = [25, 50, 75, 100]
    .map((level) => {
      const points = axes
        .map((_, i) => {
          const p = polar(cx, cy, (r * level) / 100, i * step);
          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        })
        .join(' ');
      return `<polygon points="${points}" fill="none" stroke="${level === 100 ? 'var(--tick)' : 'var(--track)'}" stroke-width="1"/>`;
    })
    .join('');

  const spokes = axes
    .map((_, i) => {
      const p = polar(cx, cy, r, i * step);
      return `<line x1="${cx}" y1="${cy}" x2="${p.x.toFixed(1)}" y2="${p.y.toFixed(1)}" stroke="var(--track)"/>`;
    })
    .join('');

  const candidatePoints = axes
    .map((axis, i) => {
      const p = polar(cx, cy, (r * Math.max(2, axis.candidate)) / 100, i * step);
      return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    })
    .join(' ');

  const dots = axes
    .map((axis, i) => {
      const p = polar(cx, cy, (r * Math.max(2, axis.candidate)) / 100, i * step);
      return `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="var(--accent-2)"
        data-tip="${esc(axis.axis)}: ${axis.candidate.toFixed(0)}% covered (${axis.skills_matched}/${axis.skills_total} skills)"/>`;
    })
    .join('');

  const labels = axes
    .map((axis, i) => {
      const p = polar(cx, cy, r + 26, i * step);
      const anchor = p.x > cx + 6 ? 'start' : p.x < cx - 6 ? 'end' : 'middle';
      const words = axis.axis.split(' ');
      const line1 = words.slice(0, 2).join(' ');
      const line2 = words.slice(2).join(' ');
      return `<text x="${p.x.toFixed(1)}" y="${p.y.toFixed(1)}" text-anchor="${anchor}" font-size="10.5"
        fill="var(--text-dim)"><tspan x="${p.x.toFixed(1)}">${esc(line1)}</tspan>${
        line2 ? `<tspan x="${p.x.toFixed(1)}" dy="12">${esc(line2)}</tspan>` : ''
      }</text>`;
    })
    .join('');

  return `
  <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img"
       aria-label="Skill coverage by category: ${esc(axes.map((a) => `${a.axis} ${a.candidate.toFixed(0)}%`).join(', '))}">
    <defs>
      <linearGradient id="radarFill" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.42"/>
        <stop offset="100%" stop-color="var(--accent-2)" stop-opacity="0.28"/>
      </linearGradient>
    </defs>
    ${rings}${spokes}
    <polygon points="${candidatePoints}" fill="url(#radarFill)" stroke="var(--accent-2)" stroke-width="2"
             style="animation: fade-up .7s var(--ease) both"/>
    ${dots}${labels}
  </svg>`;
}

/** Horizontal bars used for missing skills, component scores and ATS families. */
export function barList(items, { showValue = true, suffix = '' } = {}) {
  if (!items.length) return `<p class="small faint">Nothing to show here.</p>`;
  const max = Math.max(...items.map((i) => i.value), 1);
  return items
    .map(
      (item) => `
      <div class="bar-row" ${item.tip ? `data-tip="${esc(item.tip)}"` : ''}>
        <div class="lbl" title="${esc(item.label)}">${esc(item.label)}</div>
        <div class="track">
          <div class="fill" style="width:${((item.value / max) * 100).toFixed(1)}%;
               background:${item.color || 'linear-gradient(90deg,var(--accent),var(--accent-2))'}"></div>
        </div>
        ${showValue ? `<div class="val">${item.value.toFixed(0)}${suffix}</div>` : '<div></div>'}
      </div>`
    )
    .join('');
}

/** Readiness projection: today vs after each roadmap stage. */
export function readinessBars(readiness) {
  const rows = [
    { k: 'Today', v: readiness.current, color: 'var(--neutral)' },
    { k: 'After presentation fixes only', v: readiness.after_presentation, color: 'var(--warn)' },
    { k: 'After closing high-priority gaps', v: readiness.after_learning, color: 'var(--success)' },
  ];
  return `<div class="readiness">${rows
    .map(
      (row) => `
      <div>
        <div class="step-row"><span class="k">${esc(row.k)}</span><span class="v" style="color:${row.color}">${row.v.toFixed(0)}</span></div>
        <div class="progress"><span style="width:${Math.max(2, row.v)}%;background:${row.color}"></span></div>
      </div>`
    )
    .join('')}</div>`;
}

/** Attach hover tooltips to any element carrying `data-tip` inside `root`. */
export function activateChartTooltips(root) {
  let tip = document.getElementById('chart-tip');
  if (!tip) {
    tip = document.createElement('div');
    tip.id = 'chart-tip';
    tip.style.cssText =
      'position:fixed;z-index:300;pointer-events:none;padding:7px 11px;border-radius:9px;' +
      'background:var(--surface-2);border:1px solid var(--border-strong);font-size:0.78rem;' +
      'color:var(--text);' +
      'box-shadow:var(--shadow-lg);opacity:0;transition:opacity .13s;max-width:280px';
    document.body.appendChild(tip);
  }
  root.querySelectorAll('[data-tip]').forEach((node) => {
    node.addEventListener('mouseenter', (ev) => {
      tip.textContent = node.getAttribute('data-tip');
      tip.style.opacity = '1';
      moveTip(ev);
      if (node.tagName === 'path') node.style.opacity = '1';
    });
    node.addEventListener('mousemove', moveTip);
    node.addEventListener('mouseleave', () => {
      tip.style.opacity = '0';
      if (node.tagName === 'path') node.style.opacity = '0.88';
    });
  });

  function moveTip(ev) {
    const pad = 14;
    const width = tip.offsetWidth || 160;
    let x = ev.clientX + pad;
    if (x + width > window.innerWidth - 10) x = ev.clientX - width - pad;
    tip.style.left = `${x}px`;
    tip.style.top = `${ev.clientY + pad}px`;
  }
}
