import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, Download, Play, Plus, Sparkles, Trash2, Wand2 } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import {
  draftStudioTest, exportPlaywright, getStudioTests, planAndExecute, saveStudioTest, updateStudioTest, verifyStudioSteps,
} from '../services/api';
import { timeAgo } from '../lib/derive';

// The actions a step may use (backend: app/services/test_studio.py ACTIONS)
export const ACTIONS = [
  ['NAVIGATE', 'Open page'], ['CLICK', 'Click'], ['FILL', 'Type'], ['PRESS', 'Press key'], ['SELECT', 'Choose option'],
  ['CHECK', 'Tick'], ['UNCHECK', 'Untick'], ['HOVER', 'Hover'], ['WAIT', 'Wait'], ['RELOAD', 'Reload'],
  ['GO_BACK', 'Go back'], ['ASSERT_VISIBLE', 'Check: shown'], ['ASSERT_HIDDEN', 'Check: not shown'],
  ['ASSERT_CONTAINS_TEXT', 'Check: text contains'], ['ASSERT_HAS_TEXT', 'Check: text is'],
  ['ASSERT_VALUE', 'Check: field value is'], ['ASSERT_URL', 'Check: URL contains'], ['ASSERT_URL_EQUALS', 'Check: URL is'],
];
const NO_TARGET = new Set(['NAVIGATE', 'WAIT', 'RELOAD', 'GO_BACK', 'ASSERT_URL', 'ASSERT_URL_EQUALS']);

const STATUS = {
  found: ['green', 'On the page'],
  text: ['blue', 'By text at run time'],
  page: ['gray', 'No element needed'],
  unverified: ['orange', 'Not seen on the page'],
  invalid: ['red', 'Cannot run'],
  edited: ['gray', 'Edited: check again'],
};

const EXAMPLE = 'Log in as standard_user with password secret_sauce, add the backpack to the cart, and check the cart shows 1 item';

function StatusPill({ status }) {
  const [color, label] = STATUS[status] || STATUS.edited;
  return <span className={`pill ${color}`}>{label}</span>;
}

function saveBlob(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

const editable = (steps) => steps.map(({ action, target, value, description, status, note }) => ({
  action, target: target || '', value: value ?? '', description: description || '', status, note,
}));
const payloadSteps = (steps) => steps.map(({ action, target, value, description }) => ({
  action, target: target || null, value: value === '' && action !== 'FILL' ? null : value, description,
}));

/** The steps of a draft or saved test, editable row by row. */
function StepsEditor({ steps, onChange }) {
  const set = (i, patch) => onChange(steps.map((s, j) => (j === i ? { ...s, ...patch, status: 'edited', note: null } : s)));
  const move = (i, by) => {
    const next = [...steps];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    onChange(next);
  };
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr><th>#</th><th>Action</th><th>Element</th><th>Value</th><th>Check</th><th><span className="visually-hidden">Order</span></th></tr>
        </thead>
        <tbody>
          {steps.map((s, i) => (
            <tr key={i}>
              <td className="num">{i + 1}</td>
              <td>
                <select className="input" aria-label={`Step ${i + 1} action`} value={s.action} onChange={(e) => set(i, { action: e.target.value })}>
                  {ACTIONS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                  {!ACTIONS.some(([id]) => id === s.action) && <option value={s.action}>{s.action}</option>}
                </select>
              </td>
              <td>
                <input className="input mono" aria-label={`Step ${i + 1} element`} value={s.target} disabled={NO_TARGET.has(s.action)}
                  placeholder={NO_TARGET.has(s.action) ? '—' : '#id or button:has-text("Save")'} onChange={(e) => set(i, { target: e.target.value })} />
              </td>
              <td>
                <input className="input" aria-label={`Step ${i + 1} value`} value={s.value} onChange={(e) => set(i, { value: e.target.value })} />
              </td>
              <td>
                <div className="stack-sm">
                  <StatusPill status={s.status} />
                  {s.note && <span className="hint">{s.note}</span>}
                </div>
              </td>
              <td>
                <div className="row">
                  <button type="button" className="btn btn-sm btn-ghost" aria-label={`Move step ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={14} /></button>
                  <button type="button" className="btn btn-sm btn-ghost" aria-label={`Move step ${i + 1} down`} disabled={i === steps.length - 1} onClick={() => move(i, 1)}><ArrowDown size={14} /></button>
                  <button type="button" className="btn btn-sm btn-ghost" aria-label={`Remove step ${i + 1}`} onClick={() => onChange(steps.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function TestStudio({ onNavigate }) {
  const { projects, refresh } = useWorkspace();
  const sites = useMemo(() => projects.filter((p) => p.app_url), [projects]);
  const [projectId, setProjectId] = useState(null);
  const project = sites.find((p) => p.id === projectId) || sites[0] || null;

  const [instruction, setInstruction] = useState('');
  const [startPath, setStartPath] = useState('');
  const [draft, setDraft] = useState(null); // { name, steps, source, note, not_covered, problems, quarantine, editingId }
  const [busy, setBusy] = useState(null); // 'draft' | 'verify' | 'save' | `run-<id>`
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState([]);
  const [runs, setRuns] = useState({});

  const loadSaved = useCallback(() => {
    if (!project) return;
    getStudioTests(project.id).then(setSaved).catch((err) => setError(err.message));
  }, [project]);
  useEffect(loadSaved, [loadSaved]);

  async function act(kind, fn) {
    setBusy(kind);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  const onDraft = (e) => {
    e.preventDefault();
    act('draft', async () => {
      const res = await draftStudioTest(project.id, { instruction, start_path: startPath || null });
      setDraft({ ...res, steps: editable(res.steps), editingId: null });
    });
  };

  const onVerify = () => act('verify', async () => {
    const res = await verifyStudioSteps(project.id, { steps: payloadSteps(draft.steps), start_path: startPath || null });
    setDraft({ ...draft, ...res, steps: editable(res.steps) });
  });

  const onSave = () => act('save', async () => {
    const body = { name: draft.name, instruction: draft.instruction || instruction || null, steps: payloadSteps(draft.steps),
      start_path: startPath || null };
    if (draft.editingId) await updateStudioTest(project.id, draft.editingId, body);
    else await saveStudioTest(project.id, body);
    setDraft(null);
    setInstruction('');
    loadSaved();
    refresh?.();
  });

  const onRun = (t) => act(`run-${t.id}`, async () => {
    const res = await planAndExecute({ test_case_id: t.id });
    setRuns((prev) => ({ ...prev, [t.id]: res }));
    loadSaved();
  });

  const onEdit = (t) => {
    // The stored test opens its page first; the editor shows the steps after that
    const steps = t.steps[0]?.action === 'NAVIGATE' ? t.steps.slice(1) : t.steps;
    setDraft({ name: t.name, instruction: t.instruction, steps: editable(steps).map((s) => ({ ...s, status: 'edited' })),
      source: null, note: null, not_covered: [], problems: [], quarantine: t.quarantined, editingId: t.id });
    window.scrollTo({ top: 0 });
  };

  const onExport = (t) => act(`export-${t.id}`, async () => {
    const slug = (t.name || 'test').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'test';
    saveBlob(await exportPlaywright(t.id), `${slug}.spec.ts`);
  });

  const stale = draft?.steps.some((s) => s.status === 'edited');
  const hasCheck = draft?.steps.some((s) => s.action.startsWith('ASSERT_'));

  if (sites.length === 0) {
    return (
      <div className="page">
        <div className="page-title"><div><h1>Test Studio</h1></div></div>
        <section className="card">
          <div className="empty">
            <span className="empty-title">No project with a site yet</span>
            Run the pipeline on your site once in Autopilot; then write tests for it here in plain English.
            <button type="button" className="btn btn-sm" onClick={() => onNavigate('autopilot')}>Open Autopilot</button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Test Studio</h1>
          <p>Describe a test in plain English. TestSphere writes the steps, checks each one against your live page before
            anything runs, and keeps the saved test healed when the page changes.</p>
        </div>
      </div>

      <section className="card">
        <div className="card-head"><h3><Wand2 size={16} aria-hidden="true" /> Describe the test</h3></div>
        <form className="form-stack" onSubmit={onDraft}>
          <div className="form-row">
            <label className="field">
              Project
              <select className="input" value={project?.id || ''} onChange={(e) => { setProjectId(Number(e.target.value)); setDraft(null); }}>
                {sites.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.app_url}</option>)}
              </select>
            </label>
            <label className="field">
              Start page (optional)
              <input className="input mono" value={startPath} onChange={(e) => setStartPath(e.target.value)} placeholder="/login" />
            </label>
          </div>
          <label className="field">
            What should the test do?
            <textarea className="input" value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder={EXAMPLE}
              maxLength={2000} required minLength={3} />
          </label>
          <div className="row">
            <button type="submit" className="btn btn-primary" disabled={!project || busy === 'draft' || instruction.trim().length < 3}>
              <Sparkles size={16} /> {busy === 'draft' ? 'Reading the page and writing steps…' : 'Write the steps'}
            </button>
            <span className="hint">Nothing runs yet: you review every step first.</span>
          </div>
        </form>
        {error && <div className="alert-banner inline" role="alert">{error}</div>}
      </section>

      {draft && (
        <section className="card">
          <div className="card-head">
            <h3>{draft.editingId ? 'Edit test' : 'Review the steps'}</h3>
            {draft.source && <span className={`pill ${draft.source === 'ai' ? 'violet' : 'gray'}`}>{draft.source === 'ai' ? 'Written by AI' : 'Rule-based'}</span>}
          </div>
          {draft.note && <p className="hint m-0">{draft.note}</p>}
          {draft.not_covered?.length > 0 && (
            <div className="alert-banner inline" role="status">
              <b>Not turned into steps</b> (add them by hand or describe them differently):
              <ul className="list">{draft.not_covered.map((p) => <li key={p}>{p}</li>)}</ul>
            </div>
          )}
          <label className="field">
            Test name
            <input className="input" value={draft.name} maxLength={120} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </label>
          <StepsEditor steps={draft.steps} onChange={(steps) => setDraft({ ...draft, steps })} />
          <div className="row">
            <button type="button" className="btn btn-sm" onClick={() => setDraft({ ...draft, steps: [...draft.steps,
              { action: 'ASSERT_CONTAINS_TEXT', target: 'body', value: '', description: '', status: 'edited', note: null }] })}>
              <Plus size={14} /> Add step
            </button>
          </div>
          {draft.problems?.length > 0 && !stale && (
            <div className="alert-banner inline" role="alert"><ul className="list">{draft.problems.map((p) => <li key={p}>{p}</li>)}</ul></div>
          )}
          {draft.quarantine && !stale && (
            <p className="hint m-0">A step uses an element not seen on the page, so this test will be saved <b>quarantined</b>:
              it runs and reports, but cannot fail a run until you trust it.</p>
          )}
          <div className="card-foot">
            <span className="hint">{!hasCheck ? 'Add at least one check, or the test cannot fail.' : stale ? 'Steps changed: check them against the page again.' : 'Ready to save.'}</span>
            <div className="row">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDraft(null)}>Discard</button>
              <button type="button" className="btn btn-sm" disabled={busy === 'verify' || draft.steps.length === 0} onClick={onVerify}>
                {busy === 'verify' ? 'Checking…' : 'Check against the page'}
              </button>
              <button type="button" className="btn btn-primary btn-sm" disabled={busy === 'save' || !draft.name.trim() || !hasCheck || stale || draft.problems?.length > 0}
                onClick={onSave}>
                {busy === 'save' ? 'Saving…' : draft.editingId ? 'Save changes' : 'Save test'}
              </button>
            </div>
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-head"><h3>Saved tests</h3><span className="muted small">{saved.length}</span></div>
        <p className="card-sub">Every pipeline run of {project?.name} runs these too, on schedule and on every push.</p>
        {saved.length === 0 ? <div className="empty">No Test Studio tests in this project yet.</div> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Test</th><th>Steps</th><th>Last result</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
              <tbody>
                {saved.map((t) => {
                  const run = runs[t.id];
                  const last = run ? { status: run.status } : t.last_result;
                  return (
                    <tr key={t.id}>
                      <td>
                        <div className="stack-sm">
                          <b>{t.name}</b>
                          {t.instruction && <span className="hint">“{t.instruction}”</span>}
                          <div className="pill-row">
                            <span className="pill gray">v{t.version}</span>
                            {t.quarantined && <span className="pill orange">Quarantined</span>}
                          </div>
                        </div>
                      </td>
                      <td className="num">{t.steps.length}</td>
                      <td>
                        {last?.status ? <span className={`status ${last.status}`}>{last.status}</span> : <span className="muted small">Not run</span>}
                        {run?.error_message && <div className="hint">{run.error_message}</div>}
                        {!run && t.last_result?.finished_at && <div className="hint">{timeAgo(t.last_result.finished_at)}</div>}
                      </td>
                      <td>
                        <div className="row">
                          <button type="button" className="btn btn-sm btn-primary" disabled={busy === `run-${t.id}`} onClick={() => onRun(t)}>
                            <Play size={14} /> {busy === `run-${t.id}` ? 'Running…' : 'Run'}
                          </button>
                          <button type="button" className="btn btn-sm" onClick={() => onEdit(t)}>Edit</button>
                          <button type="button" className="btn btn-sm" aria-label={`Export ${t.name} as Playwright`} onClick={() => onExport(t)}>
                            <Download size={14} /> .spec.ts
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
