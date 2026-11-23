import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity, ArrowRight, Bot, CalendarClock, Check, CircleCheck, Code, FileText, FlaskConical, FolderPlus, Github,
  GitPullRequest, Layers, Loader, Play, Plug, Rocket, Shield, ShieldCheck, Sparkles, Timer, TriangleAlert, Wand2,
  Workflow, Wrench,
} from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { useAuth } from '../state/Auth';
import { getArtifact, getRunReportPdf, getTestExecution } from '../services/api';
import { loopModel, pct, timeAgo } from '../lib/derive';
import {
  AGENT_STATE, agentStates, clock, elapsed, finishedRuns, firstName, greeting, issueBreakdown, kpis, runBars,
} from '../lib/dashboard';

const STAGE_ICON = { ingest: Layers, qa: Bot, attack: Shield, report: FileText, remediate: Code, validate: FlaskConical, deploy: Rocket };
const AGENT_ICON = { planner: Sparkles, qa: Bot, healer: Wrench, security: Shield, remediation: Code };

function saveBlob(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/** The isometric cube cluster of the hero (colours from the theme tokens). */
function HeroArt() {
  const cube = (x, y, s, key) => (
    <g key={key}>
      <path className="cube-top" d={`M${x} ${y} l${s} ${-s / 2} l${s} ${s / 2} l${-s} ${s / 2} Z`} />
      <path className="cube-left" d={`M${x} ${y} l${s} ${s / 2} v${s} l${-s} ${-s / 2} Z`} />
      <path className="cube-right" d={`M${x + 2 * s} ${y} l${-s} ${s / 2} v${s} l${s} ${-s / 2} Z`} />
    </g>
  );
  return (
    <svg className="cubes" viewBox="0 0 400 260" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      <ellipse className="hero-shadow" cx="200" cy="215" rx="150" ry="30" />
      {[[110, 150, 45], [200, 150, 45], [155, 172, 45], [245, 172, 45], [155, 105, 45], [245, 128, 40]].map(([x, y, s], i) => cube(x, y, s, i))}
      <path className="cube-core" d="M200 70 l45 22 v50 l-45 22 l-45 -22 v-50 Z" />
      <path className="cube-mark" d="M200 96 l18 9 v20 l-18 9 l-18 -9 v-20 Z" opacity="0.92" />
    </svg>
  );
}

/** Line and area of a small series (values 0..max). */
function MiniSpark({ values, warn = false }) {
  if (!values || values.length < 2) return <svg className="mini-spark" aria-hidden="true" />;
  const W = 120;
  const H = 34;
  const max = Math.max(...values, 1e-9);
  const min = Math.min(...values, 0);
  const x = (i) => (i / (values.length - 1)) * W;
  const y = (v) => H - 3 - ((v - min) / (max - min || 1)) * (H - 6);
  const line = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  return (
    <svg className={`mini-spark ${warn ? 'warn' : ''}`} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <path className="area" d={`${line} L${W},${H} L0,${H} Z`} />
      <path className="line" d={line} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Trend({ value, points = false, lowerIsBetter = false }) {
  if (value == null) return null;
  const rounded = Math.round(value * 10) / 10;
  const good = lowerIsBetter ? rounded < 0 : rounded > 0;
  const cls = rounded === 0 ? 'flat' : good ? '' : 'bad';
  const arrow = rounded > 0 ? '↑' : rounded < 0 ? '↓' : '→';
  return (
    <span className={`kpi-trend ${cls}`} title="Latest 10 runs compared with the 10 before">
      {arrow} {rounded > 0 ? '+' : ''}{rounded}{points ? ' pts' : '%'}
    </span>
  );
}

function Kpi({ icon: Icon, tone = '', label, value, trend, series, hint }) {
  return (
    <section className="kpi" aria-label={label}>
      <div className="kpi-top">
        <span className={`kpi-icon ${tone}`}><Icon size={20} aria-hidden="true" /></span>
        <div className="kpi-text">
          <span className="kpi-label">{label}</span>
          <span className="kpi-line"><span className="kpi-value">{value}</span>{trend}</span>
        </div>
      </div>
      <MiniSpark values={series} warn={tone === 'warn'} />
      {hint && <span className="hint">{hint}</span>}
    </section>
  );
}

/** Up to four screenshots from the run's latest tests (real artifacts, sent with the sign-in token). */
function useRunShots(run) {
  const [shots, setShots] = useState([]);
  const key = run ? `${run.id}:${(run.tests || []).length}:${run.status}` : '';
  useEffect(() => {
    let alive = true;
    const urls = [];
    async function load() {
      const ids = (run?.tests || []).map((t) => t.execution_id).filter(Boolean).slice(-4);
      const found = [];
      for (const id of ids.reverse()) {
        try {
          const ex = await getTestExecution(id);
          const step = [...(ex.steps || [])].reverse().find((s) => s.screenshot);
          if (!step) continue;
          const url = URL.createObjectURL(await getArtifact(id, step.screenshot));
          urls.push(url);
          found.push({ url, label: `${(run.tests || []).find((t) => t.execution_id === id)?.name || `Test ${id}`}` });
        } catch {
          // an expired artifact is simply not shown
        }
      }
      if (alive) setShots(found);
    }
    if (run) load(); else setShots([]);
    return () => {
      alive = false;
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return shots;
}

function LiveRun({ loop, onNavigate }) {
  const run = loop.run;
  const shots = useRunShots(run);
  const [i, setI] = useState(0);
  useEffect(() => setI(0), [shots.length]);
  const shot = shots[Math.min(i, shots.length - 1)];
  return (
    <section className="live-card" aria-label="Live run">
      <div className="row-between">
        <h3>{run ? `${loop.active ? 'Live run' : 'Last run'} #${run.id}` : 'No runs yet'}</h3>
        {run && <span className={`pill ${loop.active ? 'green' : run.status === 'passed' ? 'green' : run.status === 'failed' ? 'red' : 'gray'}`}>
          {loop.active ? 'Running' : run.status}
        </span>}
      </div>
      <div className="live-screen">
        {shot ? <img src={shot.url} alt={`Screenshot: ${shot.label}`} />
          : <div className="empty">{run ? 'Screenshots appear here as tests run.' : 'Run the pipeline on your site to watch it here.'}</div>}
      </div>
      {shots.length > 1 && (
        <div className="live-dots" role="group" aria-label="Screenshots">
          {shots.map((s, n) => (
            <button key={s.url} type="button" className={n === i ? 'active' : ''} aria-label={`Show ${s.label}`} aria-pressed={n === i}
              onClick={() => setI(n)} />
          ))}
        </div>
      )}
      <div className="live-meta">
        <span>{shot?.label || run?.project_name || ''}</span>
        {run && <button type="button" className="btn btn-sm" onClick={() => onNavigate('runs', { tab: String(run.id) })}>Open</button>}
      </div>
    </section>
  );
}

function StageState({ stage }) {
  const { state, note } = stage;
  if (state === 'running') return <span className="stage-state"><Loader size={12} className="spin" aria-hidden="true" /> {note || 'Running'}</span>;
  if (state === 'done') return <span className="stage-state"><CircleCheck size={14} aria-hidden="true" /> {note || 'Done'}</span>;
  if (state === 'failed') return <span className="stage-state"><TriangleAlert size={12} aria-hidden="true" /> Failed</span>;
  if (state === 'waiting') return <span className="stage-state">{note || 'Needs you'}</span>;
  return <span className="stage-state">{state === 'skipped' ? 'Skipped' : 'Idle'}</span>;
}

function Pipeline({ loop, onNavigate }) {
  const run = loop.run;
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!loop.active) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [loop.active]);
  const seconds = run?.started_at
    ? (loop.active ? elapsed(run.started_at, now) : elapsed(run.started_at, new Date(run.finished_at || run.started_at).getTime()))
    : null;
  return (
    <section className="card">
      <div className="card-head">
        <div className="row">
          <Workflow size={22} aria-hidden="true" />
          <div>
            <h3>Autonomous Testing Pipeline {loop.active && <span className="pill green"><span className="dot" /> LIVE</span>}</h3>
            <span className="small muted">{run ? `Project: ${run.project_name} · Run #${run.id}` : 'No run yet'}</span>
          </div>
        </div>
        <div className="row">
          {seconds != null && <span className="timer" title={loop.active ? 'Running for' : 'Took'}><Timer size={14} aria-hidden="true" /> {clock(seconds)}</span>}
          {run && <button type="button" className="btn btn-primary btn-sm" onClick={() => onNavigate('runs', { tab: String(run.id) })}>View details <ArrowRight size={14} /></button>}
        </div>
      </div>
      <div className="stage-row">
        {loop.stages.map((st, n) => {
          const Icon = STAGE_ICON[st.id] || Activity;
          return (
            <React.Fragment key={st.id}>
              {n > 0 && <ArrowRight size={16} className="stage-arrow" aria-hidden="true" />}
              <button type="button" className={`stage-card ${st.state}`} onClick={() => onNavigate(st.page)}>
                <Icon size={22} className="stage-icon" aria-hidden="true" />
                {st.title}
                <StageState stage={st} />
              </button>
            </React.Fragment>
          );
        })}
      </div>
    </section>
  );
}

function TestResults({ bars }) {
  return (
    <section className="card">
      <div className="card-head"><h3>Test results <span className="small muted">(last {bars.length || 10} runs)</span></h3></div>
      {bars.length === 0 ? <div className="empty">No finished runs yet.</div> : (
        <>
          <div className="bars-wrap">
            <div className="bars-axis" aria-hidden="true"><span>100%</span><span>75%</span><span>50%</span><span>25%</span><span>0%</span></div>
            <div className="bars" role="img" aria-label={`Pass rate of the last ${bars.length} runs: ${bars.map((b) => `run ${b.id} ${pct(b.rate, 0)}`).join(', ')}`}>
              {bars.map((b) => (
                <div key={b.id} className="bar-col" title={`Run #${b.id}: ${pct(b.rate, 1)} passed`}>
                  <div className={`bar ${b.status === 'failed' ? 'failed' : ''}`} style={{ height: `${Math.max(1, (b.rate || 0) * 100)}%` }} />
                </div>
              ))}
            </div>
          </div>
          <div className="bar-labels" aria-hidden="true">{bars.map((b) => <span key={b.id}>{b.label}</span>)}</div>
        </>
      )}
    </section>
  );
}

function IssueBreakdown({ data, onNavigate }) {
  const R = 52;
  const C = 2 * Math.PI * R;
  let offset = 0;
  return (
    <section className="card">
      <div className="card-head"><h3>Issue breakdown</h3><button type="button" className="btn btn-ghost btn-sm" onClick={() => onNavigate('security')}>Open</button></div>
      <div className="donut-wrap">
        <svg className="donut" viewBox="0 0 140 140" role="img" aria-label={`${data.total} open issues`}>
          <circle className="track" cx="70" cy="70" r={R} strokeWidth="16" />
          {data.parts.map((p, n) => {
            const len = p.share * C;
            const el = (
              <circle key={p.label} className={`seg c${n + 1}`} cx="70" cy="70" r={R} strokeWidth="16"
                strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-offset} transform="rotate(-90 70 70)" />
            );
            offset += len;
            return el;
          })}
          <text className="donut-total" x="70" y="72" textAnchor="middle">{data.total}</text>
          <text className="donut-sub" x="70" y="90" textAnchor="middle">Open issues</text>
        </svg>
        {data.total === 0 ? <p className="hint m-0">No open findings and no failed tests in the latest run.</p> : (
          <ul className="legend">
            {data.parts.map((p, n) => (
              <li key={p.label}><span className={`swatch c${n + 1}`} /><span>{p.label} ({p.count})</span><span className="muted">{pct(p.share, 1)}</span></li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

const FEED_ICON = { pipeline: Workflow, heal: Wand2, security: ShieldCheck, scan: ShieldCheck, qa: FlaskConical, patch: GitPullRequest, deploy: Rocket, integration: Plug };

function RecentActivity({ audit, onNavigate }) {
  const items = audit.slice(0, 5);
  return (
    <section className="card">
      <div className="card-head"><h3>Recent activity</h3><button type="button" className="btn btn-ghost btn-sm" onClick={() => onNavigate('audit')}>View all <ArrowRight size={14} /></button></div>
      {items.length === 0 ? <div className="empty">Nothing yet.</div> : (
        <ul className="feed">
          {items.map((a) => {
            const Icon = FEED_ICON[a.kind] || (/pull request/i.test(a.message) ? Github : Activity);
            return (
              <li key={a.id}>
                <Icon size={18} aria-hidden="true" />
                <span className="feed-msg" title={a.message}>{a.message}</span>
                <span className="feed-time">{timeAgo(a.at)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Agents({ agents, onNavigate }) {
  const busy = agents.filter((a) => ['active', 'scanning'].includes(a.state)).length;
  return (
    <section className="card">
      <div className="card-head">
        <h3><Bot size={18} aria-hidden="true" /> AI agents</h3>
        <span className={`pill ${busy ? 'green' : 'gray'}`}>{busy} active</span>
      </div>
      <ul className="agent-list">
        {agents.map((a) => {
          const Icon = AGENT_ICON[a.id] || Bot;
          const [color, label] = AGENT_STATE[a.state] || AGENT_STATE.idle;
          return (
            <li key={a.id} title={a.about}>
              <Icon size={18} aria-hidden="true" />
              <span>{a.name}</span>
              <span className={`pill ${color}`}>{label}</span>
            </li>
          );
        })}
      </ul>
      <button type="button" className="btn btn-sm btn-ghost" onClick={() => onNavigate('agents')}>All agents <ArrowRight size={14} /></button>
    </section>
  );
}

function QuickActions({ latest, onNavigate }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function report() {
    setBusy(true);
    setError(null);
    try {
      saveBlob(await getRunReportPdf(latest.id), `testsphere-run-${latest.id}-report.pdf`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card">
      <div className="card-head"><h3>Quick actions</h3></div>
      <div className="quick-grid">
        <button type="button" className="quick" onClick={() => onNavigate('autopilot')}><FolderPlus size={22} aria-hidden="true" />New project</button>
        <button type="button" className="quick" onClick={() => onNavigate('schedules')}><CalendarClock size={22} aria-hidden="true" />Schedule run</button>
        <button type="button" className="quick" disabled={!latest || busy} onClick={report}
          title={latest ? `PDF report of run #${latest.id}` : 'No finished run yet'}>
          <FileText size={22} aria-hidden="true" />{busy ? 'Preparing…' : 'Generate report'}
        </button>
        <button type="button" className="quick" onClick={() => onNavigate('integrations')}><Plug size={22} aria-hidden="true" />Create integration</button>
      </div>
      {error && <div className="alert-banner inline" role="alert">{error}</div>}
    </section>
  );
}

export default function CommandCenter({ onNavigate }) {
  const ws = useWorkspace();
  const auth = useAuth();
  const loop = useMemo(() => loopModel(ws), [ws]);
  const k = useMemo(() => kpis(ws), [ws.pipelineRuns, ws.executions, ws.executionTotals, ws.findings]); // eslint-disable-line react-hooks/exhaustive-deps
  const bars = useMemo(() => runBars(ws.pipelineRuns), [ws.pipelineRuns]);
  const issues = useMemo(() => issueBreakdown(ws), [ws.pipelineRuns, ws.findings]); // eslint-disable-line react-hooks/exhaustive-deps
  const agents = useMemo(() => agentStates(ws, loop), [ws, loop]);
  const latest = finishedRuns(ws.pipelineRuns)[0] || null;
  const name = firstName(auth.mode === 'firebase' ? auth.user?.name : ws.operator);

  return (
    <div className="page">
      <div className="dash">
        <div className="dash-col">
          <div className="hero">
            <div>
              <p className="hero-greet">{greeting()}{name ? `, ${name}` : ''}</p>
              <h1 className="hero-title">Your Autonomous QA <br />&amp; Self-Healing Platform</h1>
              <p className="hero-sub">Test, detect, fix and deploy, all powered by AI agents.</p>
              <div className="row">
                <button type="button" className="btn btn-primary btn-lg" onClick={() => onNavigate('autopilot')}><Play size={18} /> Run new test</button>
                <button type="button" className="btn btn-lg" onClick={() => onNavigate('integrations')}><Github size={18} /> Connect repository</button>
              </div>
            </div>
            <div className="hero-art">
              <HeroArt />
              <span className="hero-chip c1"><Check size={16} aria-hidden="true" /><span>Test<small>AI-driven testing</small></span></span>
              <span className="hero-chip c2"><Shield size={16} aria-hidden="true" /><span>Secure<small>Find vulnerabilities</small></span></span>
              <span className="hero-chip c3"><Wrench size={16} aria-hidden="true" /><span>Heal<small>Auto-fix locators</small></span></span>
              <span className="hero-chip c4"><Rocket size={16} aria-hidden="true" /><span>Deploy<small>Verify &amp; release</small></span></span>
            </div>
          </div>

          <div className="kpi-row">
            <Kpi icon={CircleCheck} label="Pass rate" value={pct(k.passRate.value, 1)} series={k.passRate.series}
              trend={<Trend value={k.passRate.trend} points />} />
            <Kpi icon={FlaskConical} tone="violet" label="Tests executed" value={(k.testsExecuted.value || 0).toLocaleString()}
              series={k.testsExecuted.series} trend={<Trend value={k.testsExecuted.trend} />} />
            <Kpi icon={TriangleAlert} tone="warn" label="Issues detected" value={k.issues.value} series={k.issues.series}
              trend={<Trend value={k.issues.trend} lowerIsBetter />} />
            <Kpi icon={Wand2} label="Self-healing success" value={pct(k.healing.value, 1)} series={k.healing.series}
              hint={k.healing.attempts ? `${k.healing.attempts} broken locator(s) seen` : 'No broken locators yet'} />
          </div>

          <Pipeline loop={loop} onNavigate={onNavigate} />

          <div className="grid-3">
            <TestResults bars={bars} />
            <IssueBreakdown data={issues} onNavigate={onNavigate} />
            <RecentActivity audit={ws.audit || []} onNavigate={onNavigate} />
          </div>
        </div>

        <div className="dash-col">
          <LiveRun loop={loop} onNavigate={onNavigate} />
          <Agents agents={agents} onNavigate={onNavigate} />
          <QuickActions latest={latest} onNavigate={onNavigate} />
        </div>
      </div>
    </div>
  );
}
