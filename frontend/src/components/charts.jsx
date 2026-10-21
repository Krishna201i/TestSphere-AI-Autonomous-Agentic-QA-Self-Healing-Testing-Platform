/**
 * Small SVG charts used by the Command Center cards.
 */
import React from 'react';

/** Radar of exposure per category; values in [0, 1]. */
export function RadarChart({ values, labels, size = 240 }) {
  const c = size / 2;
  const r = size / 2 - 22;
  const n = values.length;
  const point = (i, v) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    return [c + Math.cos(a) * r * v, c + Math.sin(a) * r * v];
  };
  // Small floor so an all-clear scan still draws a visible shape
  const shape = values.map((v, i) => point(i, Math.max(v, 0.06)).join(',')).join(' ');

  return (
    <svg viewBox={`0 0 ${size} ${size}`} width="100%" style={{ maxWidth: size }} role="img"
      aria-label={`Exposure radar: ${labels.map((l, i) => `${l} ${Math.round(values[i] * 100)}%`).join(', ')}`}>
      <defs>
        <radialGradient id="radarBg" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#f3f1fb" />
          <stop offset="100%" stopColor="#e9e6f2" />
        </radialGradient>
        <linearGradient id="radarFill" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#7c6ff2" stopOpacity="0.75" />
          <stop offset="100%" stopColor="#5fb6a8" stopOpacity="0.6" />
        </linearGradient>
      </defs>
      <circle cx={c} cy={c} r={r + 14} fill="url(#radarBg)" stroke="#dedbe6" />
      {[0.25, 0.5, 0.75, 1].map((k) => (
        <circle key={k} cx={c} cy={c} r={r * k} fill="none" stroke="#cfcbdc" strokeWidth="1" />
      ))}
      {values.map((_, i) => {
        const [x, y] = point(i, 1);
        return <line key={i} x1={c} y1={c} x2={x} y2={y} stroke="#cfcbdc" strokeWidth="1" />;
      })}
      <polygon points={shape} fill="url(#radarFill)" stroke="#3b3570" strokeWidth="1.6" />
      {values.map((v, i) => {
        const [x, y] = point(i, Math.max(v, 0.06));
        return <circle key={i} cx={x} cy={y} r="3.6" fill="#fff" stroke="#3b3570" strokeWidth="1.6" />;
      })}
      {labels.map((l, i) => {
        const [x, y] = point(i, 1.17);
        return (
          <text key={l} x={x} y={y} fontSize="10" fill="#6d6f7c" textAnchor="middle" dominantBaseline="middle">{l}</text>
        );
      })}
    </svg>
  );
}

/** Vertical bars; the last bar is highlighted as "current". */
export function Bars({ values, height = 92 }) {
  const max = Math.max(1, ...values);
  const slots = Math.max(values.length, 12);
  const padded = [...Array(slots - values.length).fill(null), ...values];
  const w = 100 / slots;
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" width="100%" height={height}
      role="img" aria-label={`Findings per scan: ${values.join(', ') || 'no scans yet'}`}>
      {padded.map((v, i) => {
        const isLast = i === padded.length - 1 && v != null;
        const h = v == null ? 2 : Math.max(3, (v / max) * (height - 4));
        return (
          <rect key={i} x={i * w + w * 0.18} y={height - h} width={w * 0.64} height={h} rx="0.6"
            fill={v == null ? '#e4e1ea' : isLast ? '#4fae74' : '#cfcae4'} />
        );
      })}
    </svg>
  );
}

/** Progress ring; value in [0, 1] or null (no data). */
export function Ring({ value, color = 'var(--green)', size = 70 }) {
  const stroke = 7;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const v = value == null ? 0 : value;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
      aria-label={value == null ? 'no data' : `${Math.round(v * 100)} percent`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e7e3dc" strokeWidth={stroke} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke}
        strokeLinecap="round" strokeDasharray={`${circ * v} ${circ}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" fontSize="13" fontWeight="600" fill="#2c2e38">
        {value == null ? '—' : `${Math.round(v * 100)}%`}
      </text>
    </svg>
  );
}

/**
 * Health waveform: success (100%) / failure (0%) per probe, drawn as a
 * smoothed area; latency is shown in the header, not on this axis.
 */
export function Waveform({ samples, height = 96 }) {
  const W = 300;
  const H = height;
  const left = 26;
  const bottom = 16;
  const plotW = W - left - 4;
  const plotH = H - bottom - 6;

  const pts = samples.map((s, i) => {
    const x = left + (samples.length <= 1 ? plotW : (i / (samples.length - 1)) * plotW);
    // Ease latency into the shape so a healthy line still breathes a little
    const v = s.ok ? Math.max(0.55, 1 - Math.min(s.ms, 900) / 2000) : 0.02;
    return [x, 6 + plotH * (1 - v)];
  });

  const path = pts.reduce((d, [x, y], i) => {
    if (i === 0) return `M${x},${y}`;
    const [px, py] = pts[i - 1];
    const mx = (px + x) / 2;
    return `${d} C${mx},${py} ${mx},${y} ${x},${y}`;
  }, '');
  const area = pts.length ? `${path} L${pts[pts.length - 1][0]},${6 + plotH} L${pts[0][0]},${6 + plotH} Z` : '';
  const span = samples.length > 1 ? Math.round((samples[samples.length - 1].t - samples[0].t) / 1000) : 0;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((k) => ({ x: left + k * plotW, label: `${Math.round(k * span)}s` }));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Backend health over the last probes">
      <defs>
        <linearGradient id="waveFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#4fae74" stopOpacity="0.45" />
          <stop offset="100%" stopColor="#4fae74" stopOpacity="0.03" />
        </linearGradient>
      </defs>
      {[['100%', 0], ['50%', 0.5], ['0%', 1]].map(([l, k]) => (
        <g key={l}>
          <text x="0" y={6 + plotH * k} fontSize="7.5" fill="#8b8d98" dominantBaseline="middle">{l}</text>
          <line x1={left} x2={W - 4} y1={6 + plotH * k} y2={6 + plotH * k} stroke="#eeebe5" />
        </g>
      ))}
      {area && <path d={area} fill="url(#waveFill)" />}
      {path && <path d={path} fill="none" stroke="#3aa864" strokeWidth="1.8" />}
      {ticks.map((t) => (
        <text key={t.x} x={t.x} y={H - 3} fontSize="7.5" fill="#8b8d98" textAnchor="middle">{t.label}</text>
      ))}
    </svg>
  );
}
