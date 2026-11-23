/**
 * The dashboard: where everything starts.
 *
 * A new user sets up a project in three steps (the app and its repository,
 * what to test, review) and starts it.  Then the dashboard follows that
 * project's run live, one step at a time, each step saying in plain words
 * what it does and what it found, with the actions that belong to it right
 * there: approve a fix as a pull request, open the results, download the
 * report, run again.  A checklist of next steps closes the loop.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft, ArrowRight, CalendarClock, Check, ChevronDown, Download, ExternalLink, FileDiff, FileText, FlaskConical,
  FolderGit2, Github, Globe, ListChecks, Loader2, Play, Plus, RotateCw, Shield, Sparkles, Target, Wand2,
} from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import {
  cancelPipelineRun, getIntegrations, getRunReportPdf, quickPipeline, runProjectPipeline, updateProject,
} from '../services/api';
import { SCHEDULES, timeAgo, urlError } from '../lib/derive';
import { RunFixProposal } from '../components/FixPatch';
import RepositoryTests from '../components/RepositoryTests';
import { Skeleton } from '../components/charts';

const ACTIVE = ['queued', 'running'];
const PROJECT_KEY = 'testsphere.home.project';

/** Every step of a run, in order, in plain words. */
export const STEPS = [
  { key: 'codebase', icon: FolderGit2, title: 'Read your code',
    about: 'Clones your repository and maps its languages, routes, dependencies and existing tests. Nothing in it runs on our servers.' },
  { key: 'analyze', icon: Globe, title: 'Open your app',
    about: 'Loads your app in a real browser and finds its forms, buttons and links.' },
  { key: 'plan', icon: ListChecks, title: 'Plan the tests',
    about: 'Turns your goal and the page into tests, and adds your repository’s Playwright tests and your Test Studio tests.' },
  { key: 'execute', icon: Play, title: 'Run the tests',
    about: 'Runs every test in a real browser, with a screenshot and a trace for each step.' },
  { key: 'heal', icon: Wand2, title: 'Self-heal broken steps',
    about: 'Repairs steps whose element moved or was renamed, and records exactly what changed.' },
  { key: 'security', icon: Shield, title: 'Security scan',
    about: 'Checks headers, cookies, CORS, TLS and forms, only on hosts you are allowed to test.' },
  { key: 'unit', icon: FlaskConical, title: 'Your repository’s own tests',
    about: 'Reads your CI results, or runs your unit tests in an isolated sandbox.' },
  { key: 'fix', icon: FileDiff, title: 'Prepare fixes',
    about: 'Turns security findings and failing tests into code changes for you to review. Nothing changes until you approve.' },
  { key: 'report', icon: FileText, title: 'Report',
    about: 'Sums up the run, compares it with the previous one and keeps the evidence.' },
];

const GOAL_EXAMPLES = [
  'log in as demo / secret and reach the dashboard',
  'search for "shoes" and add the first result to the cart',
  'sign up with a new account and check the welcome message',
];

function readStored() {
  try {
    return Number(window.localStorage.getItem(PROJECT_KEY)) || null;
  } catch {
    return null;
  }
}

function store(id) {
  try {
    window.localStorage.setItem(PROJECT_KEY, String(id));
  } catch {
    /* private mode: the choice just is not remembered */
  }
}

// ── Setup: three steps, then start ─────────────────────────────────────────

const WIZARD = ['Your app', 'What to test', 'Review and start'];

function Stepper({ step }) {
  return (
    <ol className="wizard-steps" aria-label="Setup steps">
      {WIZARD.map((label, i) => (
        <li key={label} className={i < step ? 'done' : i === step ? 'current' : ''} aria-current={i === step ? 'step' : undefined}>
          <span className="wizard-num">{i < step ? <Check size={14} aria-hidden="true" /> : i + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}

export function SetupWizard({ onStarted, onCancel }) {
  const { system } = useWorkspace();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({
    url: '', repo_url: '', prompt: '', sign_in_first: false, active_scan: false, schedule_minutes: '',
  });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  function next(e) {
    e.preventDefault();
    setError(null);
    if (step === 0) {
      const bad = urlError(form.url);
      if (bad) return setError(bad);
      if (form.repo_url.trim() && !/^https:\/\/\S+$/.test(form.repo_url.trim())) {
        return setError('The repository address should start with https:// (for example https://github.com/you/app).');
      }
    }
    if (step < WIZARD.length - 1) return setStep(step + 1);
    return start();
  }

  async function start() {
    setBusy(true);
    try {
      const run = await quickPipeline({
        url: form.url.trim(), prompt: form.prompt.trim() || null, repo_url: form.repo_url.trim() || null,
        sign_in_first: form.sign_in_first, active_scan: form.active_scan,
      });
      if (form.schedule_minutes) {
        await updateProject(run.project_id, { schedule_minutes: Number(form.schedule_minutes) }).catch(() => {});
      }
      onStarted(run);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  const repo = form.repo_url.trim();
  return (
    <section className="card wizard" aria-labelledby="wizard-title">
      <div className="wizard-head">
        <div>
          <h2 id="wizard-title">{onCancel ? 'Add a project' : 'Test your app in three steps'}</h2>
          <p className="card-sub m-0">Tell TestSphere where your app is. It does the rest, one step at a time, and shows you each result.</p>
        </div>
        {onCancel && <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>}
      </div>
      <Stepper step={step} />
      <form className="wizard-body" onSubmit={next}>
        {step === 0 && (
          <>
            <label className="field">
              Your app&apos;s address
              <input className="input" value={form.url} onChange={set('url')} placeholder="https://your-app.example/" autoFocus required />
              <span className="hint">The page to test: your live site, a staging site or a preview deployment.</span>
            </label>
            <label className="field">
              Git repository <span className="muted">(optional, recommended)</span>
              <input className="input" value={form.repo_url} onChange={set('repo_url')} placeholder="https://github.com/you/app" />
              <span className="hint">
                With it, TestSphere also reads your code, runs your own tests and proposes fixes as pull requests.
                A private repository needs access:{' '}
                <button type="button" className="link-btn" onClick={() => { window.location.hash = '/integrations'; }}>connect GitHub</button>.
              </span>
            </label>
          </>
        )}
        {step === 1 && (
          <>
            <label className="field">
              What should a user be able to do? <span className="muted">(optional, in plain English)</span>
              <textarea className="input" rows={3} value={form.prompt} onChange={set('prompt')} maxLength={500}
                placeholder="e.g. log in as demo / secret and reach the dashboard" />
            </label>
            <div className="wizard-examples" aria-label="Examples">
              {GOAL_EXAMPLES.map((g) => (
                <button key={g} type="button" className="chip" onClick={() => setForm({ ...form, prompt: g })}>{g}</button>
              ))}
            </div>
            <label className="check">
              <input type="checkbox" checked={form.sign_in_first} onChange={set('sign_in_first')} />
              Sign in first, then test the other pages signed in (put the login details in the goal above)
            </label>
            {system?.active_scan && (
              <label className="check">
                <input type="checkbox" checked={form.active_scan} onChange={set('active_scan')} />
                Active security testing: also send harmless test attacks (only for a site you own and verified)
              </label>
            )}
            <label className="field narrow">
              Run again automatically
              <select className="input" value={form.schedule_minutes} onChange={set('schedule_minutes')}>
                {SCHEDULES.map(([value, label]) => <option key={label} value={value || ''}>{label}</option>)}
              </select>
            </label>
          </>
        )}
        {step === 2 && (
          <>
            <dl className="kv wizard-summary">
              <dt>App</dt><dd className="mono cell-wrap">{form.url.trim()}</dd>
              <dt>Repository</dt><dd className="mono cell-wrap">{repo || <span className="muted">none</span>}</dd>
              <dt>Goal</dt><dd className="cell-wrap">{form.prompt.trim() || <span className="muted">explore the page and test what is there</span>}</dd>
              <dt>Schedule</dt><dd>{SCHEDULES.find(([v]) => String(v || '') === form.schedule_minutes)?.[1] || 'Off'}</dd>
            </dl>
            <p className="small m-0"><b>What happens when you start</b> (you can watch each step):</p>
            <ol className="wizard-plan">
              {STEPS.map((s) => {
                const needsRepo = !repo && ['codebase', 'unit'].includes(s.key);
                return (
                  <li key={s.key} className={needsRepo ? 'muted' : ''}>
                    <s.icon size={16} aria-hidden="true" />
                    <span><b>{s.title}</b>{needsRepo ? ' (needs a repository: skipped)' : ''}</span>
                  </li>
                );
              })}
            </ol>
          </>
        )}
        {error && <div className="error-text" role="alert">{error}</div>}
        <div className="wizard-actions">
          {step > 0 && (
            <button type="button" className="btn" onClick={() => { setError(null); setStep(step - 1); }} disabled={busy}>
              <ArrowLeft size={16} aria-hidden="true" /> Back
            </button>
          )}
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {step < WIZARD.length - 1
              ? <>Continue <ArrowRight size={16} aria-hidden="true" /></>
              : <><Sparkles size={16} aria-hidden="true" /> {busy ? 'Starting…' : 'Start testing'}</>}
          </button>
        </div>
      </form>
    </section>
  );
}

// ── The run, step by step ──────────────────────────────────────────────────

function StepIcon({ status, Icon }) {
  if (status === 'running') return <span className="step-dot running"><Loader2 size={18} className="spin" aria-label="running" /></span>;
  if (status === 'done') return <span className="step-dot done"><Check size={18} aria-label="done" /></span>;
  if (status === 'failed') return <span className="step-dot failed"><Icon size={18} aria-label="failed" /></span>;
  return <span className={`step-dot ${status || 'pending'}`}><Icon size={18} aria-hidden="true" /></span>;
}

function stepSummary(stage) {
  if (!stage) return null;
  if (stage.status === 'pending') return 'Waiting';
  if (stage.status === 'running') return 'Working on it…';
  return stage.detail;
}

/** What a finished step lets the user do next, right in place. */
function StepActions({ step, run, onNavigate }) {
  const [pdfError, setPdfError] = useState(null);
  const open = () => { window.location.hash = `/runs/${run.id}`; };
  if (step.key === 'execute' || step.key === 'heal') {
    return <button type="button" className="btn btn-sm" onClick={open}>See each test <ArrowRight size={14} aria-hidden="true" /></button>;
  }
  if (step.key === 'security') {
    return <button type="button" className="btn btn-sm" onClick={() => onNavigate('security')}>See findings <ArrowRight size={14} aria-hidden="true" /></button>;
  }
  if (step.key === 'unit' && run.unit_tests) return <RepositoryTests result={run.unit_tests} />;
  if (step.key === 'fix') {
    const ids = [run.fix_patch?.id, run.ai_fix?.id].filter(Boolean);
    return ids.length ? <div className="stack">{ids.map((id) => <RunFixProposal key={id} patchId={id} />)}</div> : null;
  }
  if (step.key === 'report') {
    return (
      <div className="row">
        <button type="button" className="btn btn-sm btn-primary" onClick={open}>Open the full report <ArrowRight size={14} aria-hidden="true" /></button>
        <button type="button" className="btn btn-sm" onClick={() => {
          setPdfError(null);
          getRunReportPdf(run.id).then((blob) => {
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `testsphere-run-${run.id}.pdf`;
            a.click();
            setTimeout(() => URL.revokeObjectURL(a.href), 1000);
          }).catch((err) => setPdfError(err.message));
        }}>
          <Download size={14} aria-hidden="true" /> PDF
        </button>
        {pdfError && <span className="error-text small" role="alert">{pdfError}</span>}
      </div>
    );
  }
  return null;
}

function hasActions(step, run) {
  if (!run || ACTIVE.includes(run.status)) return false;
  if (step.key === 'unit') return Boolean(run.unit_tests);
  if (step.key === 'fix') return Boolean(run.fix_patch?.id || run.ai_fix?.id);
  return ['execute', 'heal', 'security', 'report'].includes(step.key);
}

export function RunTimeline({ run, onNavigate }) {
  const [openKey, setOpenKey] = useState(null);
  const stages = Object.fromEntries((run?.stages || []).map((s) => [s.key, s]));
  // Open the step that needs the user: fixes to approve, else the report
  useEffect(() => {
    if (!run || ACTIVE.includes(run.status)) return;
    setOpenKey((run.fix_patch?.id && !run.fix_patch.pull_request) || run.ai_fix?.id ? 'fix' : 'report');
  }, [run?.id, run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ol className="run-steps" aria-label="Steps of this run">
      {STEPS.map((step) => {
        const stage = stages[step.key];
        const status = stage?.status || 'pending';
        const actions = hasActions(step, run);
        const expanded = actions && openKey === step.key;
        return (
          <li key={step.key} className={`timeline-step ${status}`}>
            <StepIcon status={status} Icon={step.icon} />
            <div className="timeline-body">
              <div className="row-between">
                <h4>{step.title}</h4>
                {actions && (
                  <button type="button" className="btn btn-ghost btn-sm" aria-expanded={expanded}
                    onClick={() => setOpenKey(expanded ? null : step.key)}>
                    {expanded ? 'Hide' : 'Details'} <ChevronDown size={14} className={expanded ? 'flip' : ''} aria-hidden="true" />
                  </button>
                )}
              </div>
              <p className="small muted m-0">{step.about}</p>
              {stepSummary(stage) && <p className={`small m-0 timeline-result ${status}`}>{stepSummary(stage)}</p>}
              {expanded && <div className="timeline-actions"><StepActions step={step} run={run} onNavigate={onNavigate} /></div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// ── What to do next ────────────────────────────────────────────────────────

function useGitHubConnected() {
  const [connected, setConnected] = useState(null);
  useEffect(() => {
    getIntegrations()
      .then((rows) => setConnected(Boolean((rows || []).find((r) => r.provider === 'github')?.connected)))
      .catch(() => setConnected(null));
  }, []);
  return connected;
}

/** Add the repository, right here: saved on the project, used from the next run on. */
function AddRepository({ project, onSaved }) {
  const [value, setValue] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function save(e) {
    e.preventDefault();
    const url = value.trim();
    if (!/^https:\/\/\S+$/.test(url)) {
      setError('Use the repository’s https address, for example https://github.com/you/app.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await updateProject(project.id, { repo_url: url });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }
  return (
    <form className="checklist-form" onSubmit={save}>
      <label className="field grow">
        <span className="sr-only">Git repository</span>
        <input className="input" value={value} onChange={(e) => setValue(e.target.value)} placeholder="https://github.com/you/app" />
      </label>
      <button type="submit" className="btn btn-sm btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
      {error && <div className="error-text small" role="alert">{error}</div>}
    </form>
  );
}

function ScheduleSelect({ project, onSaved }) {
  const [error, setError] = useState(null);
  async function change(e) {
    setError(null);
    try {
      await updateProject(project.id, { schedule_minutes: e.target.value ? Number(e.target.value) : null });
      await onSaved();
    } catch (err) {
      setError(err.message);
    }
  }
  return (
    <>
      <label className="field">
        <span className="sr-only">Run automatically</span>
        <select className="input select-sm" value={project.schedule_minutes || ''} onChange={change}>
          {SCHEDULES.map(([value, label]) => <option key={label} value={value || ''}>{label}</option>)}
        </select>
      </label>
      {error && <div className="error-text small" role="alert">{error}</div>}
    </>
  );
}

function NextSteps({ project, run, onNavigate }) {
  const { refresh } = useWorkspace();
  const github = useGitHubConnected();
  const [addingRepo, setAddingRepo] = useState(false);
  const proposed = [run?.fix_patch, run?.ai_fix].filter((f) => f?.id);
  const onGitHub = Boolean(project.repo_url?.includes('github.com'));
  // Only what applies to this project: a step that cannot happen is left out, not shown as done
  const items = [
    { key: 'run', done: Boolean(run), label: 'Run your first test' },
    { key: 'repo', done: Boolean(project.repo_url),
      label: 'Add your Git repository: TestSphere then reads your code, runs your own tests and proposes fixes',
      control: addingRepo
        ? <AddRepository project={project} onSaved={async () => { setAddingRepo(false); await refresh(); }} />
        : <button type="button" className="btn btn-sm" onClick={() => setAddingRepo(true)}>Add it</button> },
    proposed.length > 0 && { key: 'fixes', done: proposed.every((f) => f.pull_request),
      label: 'Review the proposed fixes and approve them as a pull request',
      control: <button type="button" className="btn btn-sm" onClick={() => document.getElementById('run-steps')?.scrollIntoView({ behavior: 'smooth' })}>Review</button> },
    onGitHub && github !== null && { key: 'github', done: github, label: 'Connect GitHub so approved fixes open pull requests under your name',
      control: <button type="button" className="btn btn-sm" onClick={() => onNavigate('integrations')}>Connect</button> },
    { key: 'schedule', done: Boolean(project.schedule_minutes), keepControl: true, label: 'Run it again automatically',
      control: <ScheduleSelect project={project} onSaved={refresh} /> },
    { key: 'studio', done: false, optional: true, label: 'Describe a test in plain English (Test Studio)',
      control: <button type="button" className="btn btn-sm" onClick={() => onNavigate('studio')}>Write one</button> },
  ].filter(Boolean);
  const left = items.filter((i) => !i.done && !i.optional).length;
  return (
    <section className="card" aria-labelledby="next-title">
      <div className="card-head">
        <h3 id="next-title">Next steps</h3>
        <span className="muted small">{left ? `${left} to do` : 'All set'}</span>
      </div>
      <ul className="checklist">
        {items.map((item) => (
          <li key={item.key} className={item.done ? 'done' : ''}>
            <div className="checklist-row">
              <span className="check-dot">{item.done ? <Check size={14} aria-label="done" /> : null}</span>
              <span className="grow">{item.label}</span>
              {(!item.done || item.keepControl) && item.key !== 'repo' && item.control}
              {item.key === 'repo' && !item.done && !addingRepo && item.control}
            </div>
            {item.key === 'repo' && !item.done && addingRepo && item.control}
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── The page ───────────────────────────────────────────────────────────────

function RunHeader({ project, run, onRun, busy, onCancel }) {
  const active = run && ACTIVE.includes(run.status);
  const total = STEPS.length;
  const finished = (run?.stages || []).filter((s) => ['done', 'skipped', 'failed'].includes(s.status)).length;
  const s = run?.summary;
  let headline = 'Not run yet';
  if (active) headline = `Testing… step ${Math.min(finished + 1, total)} of ${total}`;
  else if (run?.status === 'passed') headline = s ? `Passed · ${s.passed} of ${s.total} tests` : 'Passed';
  else if (run?.status === 'failed') headline = s ? `Needs attention · ${s.failed} of ${s.total} tests failed` : 'Needs attention';
  else if (run) headline = run.error || run.status;
  return (
    <div className={`run-banner ${active ? 'running' : run?.status || 'idle'}`}>
      <div className="min-w-0">
        <div className="small muted">{run ? `Run #${run.id} · ${timeAgo(run.started_at || run.created_at)}` : project.name}</div>
        <div className="run-headline">{headline}</div>
        {active && <div className="progress" aria-hidden="true"><span style={{ width: `${(finished / total) * 100}%` }} /></div>}
      </div>
      <div className="row">
        {active
          ? <button type="button" className="btn" onClick={onCancel} disabled={busy}>Stop</button>
          : (
            <button type="button" className="btn btn-primary" onClick={onRun} disabled={busy || !project.app_url}>
              {run ? <RotateCw size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />} {busy ? 'Starting…' : run ? 'Run again' : 'Start'}
            </button>
          )}
      </div>
    </div>
  );
}

export default function Home({ onNavigate }) {
  const { projects, pipelineRuns, refresh, refreshRuns } = useWorkspace();
  const [selectedId, setSelectedId] = useState(readStored);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const loading = pipelineRuns === null;
  const project = useMemo(() => {
    if (!projects.length) return null;
    const byRun = pipelineRuns?.[0] && projects.find((p) => p.id === pipelineRuns[0].project_id);
    return projects.find((p) => p.id === selectedId) || byRun || projects[0];
  }, [projects, pipelineRuns, selectedId]);
  const run = project ? (pipelineRuns || []).find((r) => r.project_id === project.id) || null : null;

  function choose(id) {
    setSelectedId(id);
    store(id);
  }

  async function onStarted(started) {
    setAdding(false);
    choose(started.project_id);
    await Promise.all([refresh(), refreshRuns()]);
  }

  async function runAgain() {
    setBusy(true);
    setError(null);
    try {
      await runProjectPipeline(project.id, Boolean(project.repo_url));
      await refreshRuns();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    try {
      await cancelPipelineRun(run.id);
      await refreshRuns();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <div className="page"><section className="card"><Skeleton lines={6} block /></section></div>;
  }
  const firstTime = !project;
  return (
    <div className="page home">
      <div className="page-head">
        <div>
          <h1 className="home-title">{firstTime ? 'Welcome to TestSphere' : 'Dashboard'}</h1>
          <p className="muted m-0">
            {firstTime
              ? 'Add your app and repository. TestSphere tests it, heals it, scans it and proposes fixes, step by step.'
              : 'Your project’s latest run, step by step, and what to do next.'}
          </p>
        </div>
        {!firstTime && !adding && (
          <div className="row">
            {projects.length > 1 && (
              <label className="field inline">
                <span className="sr-only">Project</span>
                <select className="input" value={project.id} onChange={(e) => choose(Number(e.target.value))}>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>
            )}
            <button type="button" className="btn" onClick={() => setAdding(true)}><Plus size={16} aria-hidden="true" /> New project</button>
          </div>
        )}
      </div>

      {(firstTime || adding) && <SetupWizard onStarted={onStarted} onCancel={firstTime ? null : () => setAdding(false)} />}

      {!firstTime && !adding && (
        <>
          <section className="card project-card" aria-label="Project">
            <div className="project-meta">
              <div className="min-w-0">
                <h2 className="m-0">{project.name}</h2>
                <div className="small muted cell-wrap">
                  <Globe size={13} className="icon-inline" aria-hidden="true" /> <a href={project.app_url} target="_blank" rel="noreferrer">{project.app_url}</a>
                  {project.repo_url && <> · <FolderGit2 size={13} className="icon-inline" aria-hidden="true" /> <a href={project.repo_url} target="_blank" rel="noreferrer">{project.repo_url.replace(/^https:\/\//, '')}</a></>}
                </div>
                {project.prompt && <div className="small cell-wrap">Goal: {project.prompt}</div>}
              </div>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => onNavigate('autopilot')}>
                Settings <ExternalLink size={13} aria-hidden="true" />
              </button>
            </div>
            <RunHeader project={project} run={run} onRun={runAgain} onCancel={cancel} busy={busy} />
            {error && <div className="error-text" role="alert">{error}</div>}
          </section>

          <div className="home-grid">
            <section className="card" id="run-steps" aria-labelledby="steps-title">
              <div className="card-head">
                <h3 id="steps-title">{run ? 'Step by step' : 'What will happen'}</h3>
                {run && <button type="button" className="btn btn-ghost btn-sm" onClick={() => { window.location.hash = `/runs/${run.id}`; }}>Full run <ArrowRight size={14} aria-hidden="true" /></button>}
              </div>
              <RunTimeline run={run} onNavigate={onNavigate} />
            </section>
            <NextSteps project={project} run={run} onNavigate={onNavigate} />
          </div>
        </>
      )}
    </div>
  );
}
