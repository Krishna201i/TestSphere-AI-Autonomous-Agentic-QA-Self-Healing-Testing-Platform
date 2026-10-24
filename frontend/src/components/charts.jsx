/**
 * Small SVG charts and motion helpers shared by the cards.  Colours come
 * from CSS classes (theme tokens), so they follow light and dark mode.
 */
import React, { useEffect, useRef, useState } from 'react';
import { usePrefersReducedMotion } from './PipelineLoop';

/** Radar of exposure per category; values in [0, 1]. */
export function RadarChart({ values, labels, size = 240 }) {
  const c = size / 2;
  const r = size / 2 - 30;
  const n = values.length;
  const point = (i, v) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    return [c + Math.cos(a) * r * v, c + Math.sin(a) * r * v];
  };
  // Small floor so an all-clear scan still draws a visible shape
  const shape = values.map((v, i) => point(i, Math.max(v, 0.06)).join(',')).join(' ');

  return (
    <svg viewBox={`0 0 ${size} ${size}`} width="100%" role="img"
      aria-label={`Exposure radar: ${labels.map((l, i) => `${l} ${Math.round(values[i] * 100)}%`).join(', ')}`}>
      <circle className="radar-bg" cx={c} cy={c} r={r + 8} />
      {[0.25, 0.5, 0.75, 1].map((k) => <circle key={k} className="radar-grid" cx={c} cy={c} r={r * k} />)}
      {values.map((_, i) => {
        const [x, y] = point(i, 1);
        return <line key={i} className="radar-grid" x1={c} y1={c} x2={x} y2={y} />;
      })}
      <polygon className="radar-shape" points={shape} />
      {values.map((v, i) => {
        const [x, y] = point(i, Math.max(v, 0.06));
        return <circle key={i} className="radar-dot" cx={x} cy={y} r="3.5" />;
      })}
      {labels.map((l, i) => {
        const [x, y] = point(i, 1.2);
        return <text key={l} className="radar-label" x={x} y={y} textAnchor="middle" dominantBaseline="middle">{l}</text>;
      })}
    </svg>
  );
}

/** Latency sparkline of the health probes; failed probes are red ticks. */
export function Sparkline({ samples, height = 40 }) {
  const W = 300;
  const ok = samples.filter((s) => s.ok);
  if (samples.length < 2) return null;
  const max = Math.max(50, ...ok.map((s) => s.ms));
  const x = (i) => (i / (samples.length - 1)) * W;
  const y = (ms) => height - 3 - (Math.min(ms, max) / max) * (height - 6);
  // One line segment per run of successful probes
  const segments = [[]];
  samples.forEach((s, i) => {
    if (s.ok) segments[segments.length - 1].push(`${x(i).toFixed(1)},${y(s.ms).toFixed(1)}`);
    else segments.push([]);
  });
  const line = segments.filter((seg) => seg.length).map((seg) => `M${seg.join(' L')}`).join(' ');
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" role="img"
      aria-label={`API latency over the last ${samples.length} checks, up to ${Math.round(max)} ms`}>
      {line && <path className="spark-line" d={line} vectorEffect="non-scaling-stroke" />}
      {samples.map((s, i) => (s.ok ? null : <rect key={i} className="spark-fail" x={x(i) - 1.5} y={0} width={3} height={height} />))}
    </svg>
  );
}

/** A number that counts up to its new value (instant with reduced motion). */
export function AnimatedNumber({ value, format = (v) => String(Math.round(v)), duration = 400 }) {
  const reduce = usePrefersReducedMotion();
  const [shown, setShown] = useState(value);
  const prev = useRef(value);
  useEffect(() => {
    if (value == null || prev.current == null || reduce) {
      prev.current = value;
      setShown(value);
      return undefined;
    }
    const start = prev.current;
    const t0 = performance.now();
    let frame;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / duration);
      const eased = 1 - (1 - k) ** 3;
      setShown(start + (value - start) * eased);
      if (k < 1) frame = requestAnimationFrame(step);
      else prev.current = value;
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value, duration, reduce]);
  return <>{shown == null ? '—' : format(shown)}</>;
}

/** Placeholder lines while data loads. */
export function Skeleton({ lines = 3, block = false }) {
  return (
    <div className="stack-sm" aria-hidden="true">
      {block && <span className="skeleton block" />}
      {Array.from({ length: lines }, (_, i) => <span key={i} className="skeleton line" />)}
    </div>
  );
}
