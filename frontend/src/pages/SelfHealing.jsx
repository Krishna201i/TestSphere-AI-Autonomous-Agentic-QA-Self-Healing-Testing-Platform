import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowRight, Check, X } from 'lucide-react';
import { getHeals, reviewHeal } from '../services/api';
import { pct, timeAgo } from '../lib/derive';
import { usePaged } from '../lib/usePaged';
import Pager from '../components/Pager';
import { Screenshot } from './RunDetail';

const FILTERS = [['pending', 'To review'], ['approved', 'Approved'], ['rejected', 'Rejected'], ['all', 'All']];
const STRATEGY = { ai_healer: 'AI healer', fingerprint: 'Fingerprint', fallback: 'Learned fallback', engine: 'Engine' };

const decisionOf = (h) => h.review?.decision || 'pending';

export default function SelfHealing() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('pending');
  const [busy, setBusy] = useState(null);

  const load = useCallback(() => {
    getHeals().then(setData).catch((err) => setError(err.message));
  }, []);
  useEffect(load, [load]);

  const heals = useMemo(() => (data?.heals || []).filter((h) => filter === 'all' || decisionOf(h) === filter), [data, filter]);
  const paged = usePaged(heals, 10);

  async function review(h, decision) {
    setBusy(h.key);
    setError(null);
    try {
      await reviewHeal(h.execution_id, h.original, decision);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Self-Healing</h1>
          <p>Every broken locator the agents repaired during a run. Approve a heal to keep it in the test; reject one that
            reached the wrong element, and that step stops healing until you update it, so it can never pass on the wrong element.</p>
        </div>
      </div>

      <div className="kpi-row">
        {[['Heals', data?.total], ['To review', data?.pending], ['Approved', data?.approved], ['Rejected', data?.rejected]].map(([label, n]) => (
          <section key={label} className="kpi" aria-label={label}>
            <span className="kpi-text">
              <span className="kpi-label">{label}</span>
              <span className="kpi-line"><span className="kpi-value">{n ?? '—'}</span></span>
            </span>
          </section>
        ))}
      </div>

      <section className="card">
        <div className="tabs" role="tablist" aria-label="Filter heals">
          {FILTERS.map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={filter === id} className={`tab ${filter === id ? 'active' : ''}`}
              onClick={() => setFilter(id)}>{label}</button>
          ))}
        </div>
        {error && <div className="alert-banner inline" role="alert">{error}</div>}
        {!data ? <div className="empty" role="status">Loading…</div> : heals.length === 0 ? (
          <div className="empty">
            <span className="empty-title">{data.total ? 'Nothing here' : 'No heals yet'}</span>
            {!data.total && 'When a page changes and a locator breaks, the repair shows up here for review.'}
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Evidence</th><th>Test and step</th><th>Locator</th><th>How</th><th>Decision</th></tr></thead>
              <tbody>
                {paged.items.map((h) => (
                  <tr key={h.key}>
                    <td>{h.screenshot ? <div className="thumb"><Screenshot executionId={h.execution_id} artifactKey={h.screenshot} alt={`Healed step of ${h.test_name}`} /></div>
                      : <span className="muted small">No screenshot</span>}</td>
                    <td>
                      <b>{h.test_name || `Test #${h.test_case_id}`}</b>
                      {h.step && <div className="hint">{h.step}</div>}
                      <div className="hint">{timeAgo(h.at)} · execution #{h.execution_id}</div>
                    </td>
                    <td>
                      <span className="arrow-pair">
                        <span className="mono small">{h.original}</span>
                        <ArrowRight size={14} aria-label="healed to" />
                        <span className="mono small">{h.selected}</span>
                      </span>
                      {h.written_back && <div className="hint">Written into the test</div>}
                    </td>
                    <td>
                      {STRATEGY[h.strategy] || h.strategy}
                      <div className="hint">confidence {pct(h.confidence, 0)}</div>
                    </td>
                    <td>
                      {h.review ? (
                        <div className="stack-sm">
                          <span className={`pill ${h.review.decision === 'approved' ? 'green' : 'red'}`}>{h.review.decision}</span>
                          <span className="hint">{h.review.by} · {timeAgo(h.review.at)}</span>
                        </div>
                      ) : null}
                      <div className="row">
                        {decisionOf(h) !== 'approved' && (
                          <button type="button" className="btn btn-sm" disabled={busy === h.key} onClick={() => review(h, 'approve')}
                            aria-label={`Approve heal of ${h.original}`}><Check size={14} /> Approve</button>
                        )}
                        {decisionOf(h) !== 'rejected' && (
                          <button type="button" className="btn btn-sm btn-danger" disabled={busy === h.key} onClick={() => review(h, 'reject')}
                            aria-label={`Reject heal of ${h.original}`}><X size={14} /> Reject</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager paged={paged} label="heals" />
      </section>
    </div>
  );
}
