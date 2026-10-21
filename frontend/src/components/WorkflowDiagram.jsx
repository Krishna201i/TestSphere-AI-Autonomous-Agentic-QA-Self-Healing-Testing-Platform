/**
 * End-to-end workflow diagram.  Geometry is laid out in a 1930×330 space
 * (matching the design) and scales with the container; text sizes use
 * container query units so the whole diagram scales as one picture.
 */
import React from 'react';

const W = 1930;
const H = 330;

const BOXES = {
  ingest: [50, 105, 257, 107],
  qa: [387, 23, 251, 105],
  attack: [387, 188, 251, 105],
  report: [723, 105, 233, 107],
  remediate: [1025, 105, 235, 107],
  validate: [1325, 105, 238, 107],
  deploy: [1632, 105, 245, 107],
};

const pct = (v, total) => `${(v / total) * 100}%`;

function Arrowhead({ id }) {
  return (
    <marker id={id} viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M1,1 L9,5 L1,9" fill="none" stroke="#3b3e4f" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </marker>
  );
}

export default function WorkflowDiagram({ stages, active, onSelect }) {
  const r = 14; // corner radius of the bracket wires
  return (
    <div className="diagram-scroll">
      <div className="diagram">
        <svg className="wires" viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
          <defs><Arrowhead id="arrow" /></defs>
          {/* 1 → 2A / 2B bracket */}
          <path className="wire" d={`M307,158 H345`} />
          <path className="wire" markerEnd="url(#arrow)" d={`M345,158 V${75 + r} Q345,75 ${345 + r},75 H383`} />
          <path className="wire" markerEnd="url(#arrow)" d={`M345,158 V${240 - r} Q345,240 ${345 + r},240 H383`} />
          {/* 2A / 2B → 3 bracket */}
          <path className="wire" d={`M638,75 H${678 - r} Q678,75 678,${75 + r} V158`} />
          <path className="wire" d={`M638,240 H${678 - r} Q678,240 678,${240 - r} V158`} />
          <path className="wire" markerEnd="url(#arrow)" d="M678,158 H719" />
          {/* 3 → 4 → 5 → 6 */}
          <path className="wire" markerEnd="url(#arrow)" d="M956,158 H1013" />
          <path className="wire" markerEnd="url(#arrow)" d="M1272,158 H1321" />
          <path className="wire" markerEnd="url(#arrow)" d="M1563,158 H1628" />
          {/* Self-healing retry loop: 6 → back to 4 */}
          <path className="wire loop" markerEnd="url(#arrow)"
            d={`M1755,214 V${277 - r} Q1755,277 ${1755 - r},277 H${1142 + r} Q1142,277 1142,${277 - r} V226`} />
        </svg>

        {stages.map((s) => {
          const [x, y, w, h] = BOXES[s.id];
          return (
            <button
              type="button"
              key={s.id}
              className={`node ${active === s.id ? 'active' : ''}`}
              style={{ left: pct(x, W), top: pct(y, H), width: pct(w, W), height: pct(h, H) }}
              onClick={() => onSelect?.(s)}
              title={`${s.status === 'live' ? 'Live' : s.status === 'partial' ? 'Partially built' : 'Planned'} — ${s.detail}`}
            >
              <span className={`node-state ${s.status}`} />
              <span className="node-title">{s.num} {s.title}</span>
              <span className={`pill ${s.tone}`}>{s.badge}</span>
            </button>
          );
        })}

        <div className="loop-label" style={{ left: pct(1448, W), top: pct(306, H) }}>
          <LoopIcon />
          Self-Healing Retry Loop
          <LoopIcon flip />
        </div>
      </div>
    </div>
  );
}

function LoopIcon({ flip }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      style={flip ? { transform: 'scaleX(-1)' } : undefined} aria-hidden="true">
      <path d="M4 8h13l-3-3M20 16H7l3 3" />
    </svg>
  );
}

export function StageLegend() {
  return (
    <div className="legend">
      <span><i style={{ background: 'var(--green)' }} /> Live</span>
      <span><i style={{ background: 'var(--amber)' }} /> Partially built</span>
      <span><i style={{ background: '#b9b4ab' }} /> Planned</span>
      <span>Glowing stage = needs attention now · click a stage to open it</span>
    </div>
  );
}
