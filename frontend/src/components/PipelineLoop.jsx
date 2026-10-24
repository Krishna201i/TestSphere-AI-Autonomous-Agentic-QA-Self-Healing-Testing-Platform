/**
 * The testing loop: seven stages on a closed track, 1 → 2A → 2B → 3 → 4 → 5
 * → 6 and back to 1.  A failed retest (5) goes back to remediation (4).
 *
 * Geometry lives in a 1200×560 box that scales with its container; text uses
 * container units.  Live state comes from loopModel(): the running stage
 * pulses, a token travels into it along the track, and the track fills as the
 * run gets further round.  Below 720px the loop becomes an ordered list.
 */
import React, { useEffect, useId, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, Circle, CircleDashed, Clock3, Loader2, MinusCircle, Play, RotateCcw, Search, XCircle,
} from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { loopModel, timeAgo } from '../lib/derive';

const VB_W = 1200;
const VB_H = 560;
const X0 = 110;
const X1 = 1090;
const Y0 = 100;
const Y1 = 460;
const R = 110;
const ARC = (Math.PI / 2) * R;

// Clockwise from stage 1 (top left) round the track and back
const TRACK = `M290,${Y0} H${X1 - R} A${R},${R} 0 0 1 ${X1},${Y0 + R} V${Y1 - R} A${R},${R} 0 0 1 ${X1 - R},${Y1} `
  + `H${X0 + R} A${R},${R} 0 0 1 ${X0},${Y1 - R} V${Y0 + R} A${R},${R} 0 0 1 ${X0 + R},${Y0} Z`;
const TOP = X1 - R - 290;
const SIDE = Y1 - Y0 - 2 * R;
const BOTTOM = X1 - X0 - 2 * R;
const TOTAL = TOP + SIDE * 2 + BOTTOM + 4 * ARC + (290 - X0 - R);

// Where each stage sits: [x, y, distance along the track from stage 1]
const PLACES = {
  ingest: [290, Y0, 0],
  qa: [590, Y0, 300],
  attack: [890, Y0, 600],
  report: [X1, (Y0 + Y1) / 2, TOP + ARC + SIDE / 2],
  remediate: [890, Y1, TOP + 2 * ARC + SIDE + (X1 - R - 890)],
  validate: [590, Y1, TOP + 2 * ARC + SIDE + (X1 - R - 590)],
  deploy: [290, Y1, TOP + 2 * ARC + SIDE + (X1 - R - 290)],
};
const ORDER = Object.keys(PLACES);

const STATE_TEXT = {
  running: 'Running', done: 'Done', failed: 'Failed', waiting: 'Needs you', skipped: 'Skipped',
  pending: 'Queued', idle: 'Ready', planned: 'Planned',
};

function StateIcon({ state }) {
  const props = { className: `n-icon${state === 'running' ? ' spin' : ''}`, 'aria-hidden': true };
  if (state === 'running') return <Loader2 {...props} />;
  if (state === 'done') return <CheckCircle2 {...props} />;
  if (state === 'failed') return <XCircle {...props} />;
  if (state === 'waiting') return <AlertTriangle {...props} />;
  if (state === 'skipped') return <MinusCircle {...props} />;
  if (state === 'pending') return <Clock3 {...props} />;
  if (state === 'planned') return <CircleDashed {...props} />;
  return <Circle {...props} />;
}

export function usePrefersReducedMotion() {
  const query = '(prefers-reduced-motion: reduce)';
  const [reduce, setReduce] = useState(() => typeof window !== 'undefined' && window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return undefined;
    const on = () => setReduce(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return Boolean(reduce);
}

function StageButton({ stage, onSelect, style }) {
  return (
    <button type="button" className={`loop-node ${stage.state}`} style={style} onClick={() => onSelect(stage)} title={stage.about}>
      <span className="n-top">
        <span className="n-num">{stage.num}</span>
        <StateIcon state={stage.state} />
      </span>
      <span className="n-title">{stage.title}</span>
      <span className="n-state">{stage.note ? <><span className="visually-hidden">{STATE_TEXT[stage.state]}: </span>{stage.note}</> : STATE_TEXT[stage.state]}</span>
    </button>
  );
}

function Chevron({ x, y, angle, className = 'loop-arrow' }) {
  return <path className={className} d="M-7,-7 L5,0 L-7,7 Z" transform={`translate(${x} ${y}) rotate(${angle})`} />;
}

function Hub({ model, onNavigate }) {
  const { run, active, running, cycles, attention } = model;
  if (!run) {
    return (
      <>
        <span className="hub-kicker">No runs yet</span>
        <span className="hub-title">Start your first cycle</span>
        <span className="hub-sub">Give Autopilot a URL. It runs stages 1 to 3, then fixes and retests come back here.</span>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => onNavigate('autopilot')}><Play size={14} /> Run the pipeline</button>
      </>
    );
  }
  if (active) {
    return (
      <>
        <span className="hub-kicker">Run #{run.id} · {run.status}</span>
        <span className="hub-title">{run.project_name}</span>
        <span className="hub-sub">{running ? `${running.title}: ${running.note || 'working'}` : 'Waiting for a worker'}</span>
        <div className="meter" role="progressbar" aria-label="Run progress" aria-valuemin={0} aria-valuemax={100}
          aria-valuenow={Math.round(model.progress * 100)}>
          <span style={{ width: `${Math.round(model.progress * 100)}%` }} />
        </div>
      </>
    );
  }
  const s = run.summary;
  const passed = run.status === 'passed';
  return (
    <>
      <span className="hub-kicker">Last run #{run.id} · {timeAgo(run.finished_at || run.started_at || run.created_at)}</span>
      <span className={`hub-title ${passed ? 'ok-text' : 'bad-text'}`}>
        {s ? `${s.passed} of ${s.total} tests passed` : passed ? 'Passed' : 'Failed'}
      </span>
      <span className="hub-sub">
        {attention.length
          ? `Next: ${attention.map((a) => a.note).join(' · ')}`
          : `${cycles} cycle${cycles === 1 ? '' : 's'} completed · ${run.project_name}`}
      </span>
      <div className="row">
        <button type="button" className="btn btn-sm" onClick={() => onNavigate('autopilot')}>Open run</button>
        {attention[0] && (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => onNavigate(attention[0].page)}>
            Go to {attention[0].short.toLowerCase()}
          </button>
        )}
      </div>
    </>
  );
}

export function PipelineLoop({ onNavigate }) {
  const ws = useWorkspace();
  const model = loopModel(ws);
  const reduce = usePrefersReducedMotion();
  const pathId = `loop-track-${useId().replace(/:/g, '')}`;
  const byId = Object.fromEntries(model.stages.map((s) => [s.id, s]));
  const select = (s) => onNavigate(s.page);

  // Track fill: up to the furthest stage this run reached
  const reachedId = model.reached >= 0 ? model.stages[model.reached].id : null;
  const filled = reachedId ? PLACES[reachedId][2] : 0;
  const tone = model.active ? '' : model.run?.status === 'passed' ? 'passed' : model.run ? 'failed' : '';

  // Token: from the previous stage into the running one
  const runIdx = model.running ? ORDER.indexOf(model.running.id) : -1;
  const from = runIdx > 0 ? PLACES[ORDER[runIdx - 1]][2] : 0;
  const to = runIdx >= 0 ? PLACES[ORDER[runIdx]][2] : 0;

  return (
    <div className="loop-wrap">
      <div className={`loop ${model.active || model.running ? 'running' : ''}`}>
        <svg className="loop-svg" viewBox={`0 0 ${VB_W} ${VB_H}`} aria-hidden="true">
          <path id={pathId} className="loop-track" d={TRACK} />
          <path className="loop-flow" d={TRACK} />
          {filled > 0 && (
            <path className={`loop-progress ${tone}`} d={TRACK} strokeDasharray={`${filled} ${TOTAL}`} />
          )}
          {/* Direction of travel */}
          <Chevron x={440} y={Y0} angle={0} />
          <Chevron x={740} y={Y0} angle={0} />
          <Chevron x={X1} y={Y0 + R + 20} angle={90} />
          <Chevron x={X1} y={Y1 - R - 20} angle={90} />
          <Chevron x={740} y={Y1} angle={180} />
          <Chevron x={440} y={Y1} angle={180} />
          <Chevron x={X0} y={(Y0 + Y1) / 2} angle={-90} />
          <text className="loop-label" x={X0 + 24} y={(Y0 + Y1) / 2 + 5}>Next cycle</text>
          {/* Retest failed: 5 → back to 4 */}
          <path className="loop-retry" d={`M830,${Y1 - 58} C780,${Y1 - 96} 700,${Y1 - 96} 650,${Y1 - 58}`} />
          <Chevron x={830} y={Y1 - 60} angle={40} className="loop-arrow retry" />
          <text className="loop-label" x={740} y={Y1 - 98} textAnchor="middle">Retest fails, fix again</text>
          {runIdx >= 0 && !reduce && (
            <circle r="8" className="loop-token">
              <animateMotion dur="1.6s" repeatCount="indefinite" calcMode="linear"
                keyPoints={`${(from / TOTAL).toFixed(4)};${(to / TOTAL).toFixed(4)}`} keyTimes="0;1">
                <mpath href={`#${pathId}`} />
              </animateMotion>
            </circle>
          )}
        </svg>

        {ORDER.map((id) => {
          const [x, y] = PLACES[id];
          return <StageButton key={id} stage={byId[id]} onSelect={select} style={{ left: `${(x / VB_W) * 100}%`, top: `${(y / VB_H) * 100}%` }} />;
        })}

        <div className="loop-hub" aria-live="polite"><Hub model={model} onNavigate={onNavigate} /></div>
      </div>

      {/* Narrow screens */}
      <div className="loop-mobile-hub" aria-live="polite"><Hub model={model} onNavigate={onNavigate} /></div>
      <ol className="loop-list" aria-label="Testing loop stages">
        {model.stages.map((s) => <li key={s.id}><StageButton stage={s} onSelect={select} /></li>)}
        <li className="loop-back"><RotateCcw size={14} aria-hidden="true" /> Back to 1 for the next cycle</li>
      </ol>
    </div>
  );
}

export function LoopLegend() {
  return (
    <div className="loop-legend">
      <span><i className="running" /> Running</span>
      <span><i className="done" /> Done</span>
      <span><i className="waiting" /> Needs you</span>
      <span><i className="failed" /> Failed</span>
      <span><i className="planned" /> Planned</span>
      <span>Click a stage to open it</span>
    </div>
  );
}

/** Loop with its heading; Home and the Visualizer both lead with it. */
export default function LoopPanel({ onNavigate, title = 'Autonomous testing loop', search = true }) {
  const [query, setQuery] = useState('');
  return (
    <section className="loop-panel" aria-labelledby="workflow-title">
      <div className="loop-head">
        <div>
          <h2 id="workflow-title">{title}</h2>
          <p>Ingest, test, report, fix, verify and deploy, then round again. Each stage shows its live state.</p>
        </div>
        {search && (
          <form className="search" role="search" onSubmit={(e) => { e.preventDefault(); onNavigate('audit', { query }); }}>
            <Search size={16} aria-hidden="true" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search logs and findings" aria-label="Search logs and findings" />
          </form>
        )}
      </div>
      <PipelineLoop onNavigate={onNavigate} />
      <LoopLegend />
    </section>
  );
}
