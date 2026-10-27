import React, { useState } from 'react';
import { FolderGit2 } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { timeAgo } from '../lib/derive';

const LANG_COLORS = [1, 2, 3, 4, 5, 6, 7].map((n) => `var(--chart-${n})`);

function BlueprintView({ bp }) {
  const langs = Object.entries(bp.languages || {});
  const totalLines = langs.reduce((n, [, v]) => n + v.lines, 0) || 1;
  const testFiles = (bp.test_suites || []).reduce((n, s) => n + s.files, 0);
  const deps = Object.entries(bp.dependencies || {});

  return (
    <div className="stack-lg">
      <div className="stat-tiles">
        <div className="stat-tile"><div className="v">{bp.files_total}{bp.truncated ? '+' : ''}</div><div className="l">files analyzed</div></div>
        <div className="stat-tile"><div className="v">{langs[0]?.[0] || '—'}</div><div className="l">main language</div></div>
        <div className="stat-tile"><div className="v">{bp.routes.length}</div><div className="l">HTTP routes found</div></div>
        <div className="stat-tile"><div className="v">{testFiles}</div><div className="l">existing test files</div></div>
        <div className="stat-tile"><div className={`v ${bp.risks.length ? 'bad' : 'good'}`}>{bp.risks.length}</div><div className="l">static risks</div></div>
      </div>

      {langs.length > 0 && (
        <div>
          <div className="lang-bar" aria-hidden="true">
            {langs.map(([name, v], i) => (
              <span key={name} style={{ width: `${(v.lines / totalLines) * 100}%`, background: LANG_COLORS[i % LANG_COLORS.length] }} />
            ))}
          </div>
          <div className="lang-legend">
            {langs.map(([name, v], i) => (
              <span key={name}><i className="swatch" style={{ background: LANG_COLORS[i % LANG_COLORS.length] }} />{name} {Math.round((v.lines / totalLines) * 100)}% · {v.files} files</span>
            ))}
          </div>
        </div>
      )}

      <div className="grid-2">
        <div>
          <h4 className="section-title">Frameworks</h4>
          <div className="pill-row">
            {bp.frameworks.length ? bp.frameworks.map((f) => <span key={f} className="pill blue">{f}</span>) : <span className="muted small">None detected</span>}
          </div>
          <h4 className="section-title mt-3">Existing test suites</h4>
          {bp.test_suites.length ? (
            <ul className="small list">
              {bp.test_suites.map((s) => <li key={s.framework}><b>{s.framework}</b>: {s.files} file(s) <span className="muted mono">{s.examples.slice(0, 2).join(', ')}</span></li>)}
            </ul>
          ) : <span className="muted small">No tests found</span>}
          <h4 className="section-title mt-3">Entry points</h4>
          {bp.entry_points.length ? (
            <ul className="small mono list">{bp.entry_points.slice(0, 8).map((e) => <li key={e}>{e}</li>)}</ul>
          ) : <span className="muted small">None detected</span>}
          <h4 className="section-title mt-3">Dependencies</h4>
          {deps.length ? deps.map(([eco, names]) => (
            <div key={eco} className="small"><b>{eco}</b> ({names.length}): <span className="muted">{names.slice(0, 12).join(', ')}{names.length > 12 ? '…' : ''}</span></div>
          )) : <span className="muted small">No manifest found</span>}
        </div>

        <div>
          <h4 className="section-title">Static risks</h4>
          {bp.risks.length === 0 ? <div className="small ok-text">No committed secrets, .env files or debug flags found.</div> : (
            <div className="table-wrap scroll-y">
              <table className="table">
                <tbody>
                  {bp.risks.map((r, i) => (
                    <tr key={i}>
                      <td><span className="sev high">{r.kind}</span></td>
                      <td className="mono small cell-wrap">{r.file}{r.line ? `:${r.line}` : ''}<div className="muted font-sans">{r.detail}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h4 className="section-title mt-3">HTTP routes (QA &amp; attack surface)</h4>
          {bp.routes.length === 0 ? <span className="muted small">No routes detected</span> : (
            <div className="table-wrap scroll-y">
              <table className="table">
                <tbody>
                  {bp.routes.slice(0, 100).map((r, i) => (
                    <tr key={i}>
                      <td className="mono small"><b>{r.method}</b></td>
                      <td className="mono small cell-wrap">{r.path}</td>
                      <td className="mono small muted cell-wrap">{r.file}:{r.line}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function CodebaseIngestion() {
  const { ingest, ingesting, blueprint, blueprints, openBlueprint, system } = useWorkspace();
  const [source, setSource] = useState('');
  const [error, setError] = useState(null);
  const allowLocal = system?.ingestion?.local_paths;
  // newest analysis per source
  const previous = blueprints.filter((b, i) => blueprints.findIndex((x) => x.source === b.source) === i);

  async function onSubmit(e) {
    e.preventDefault();
    setError(null);
    try {
      await ingest(source.trim());
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="card" id="ingestion">
      <div className="card-head">
        <h3><FolderGit2 size={18} aria-hidden="true" />Codebase Ingestion</h3>
        <span className="pill gray">1 · Ingest</span>
      </div>
      <form className="form-row" onSubmit={onSubmit}>
        <label className="field wide">
          {allowLocal ? 'Public Git URL or local folder path' : 'Public Git URL'}
          <input className="input" value={source} onChange={(e) => setSource(e.target.value)} required
            placeholder={allowLocal ? 'https://github.com/owner/repo   or   C:\\path\\to\\your\\project' : 'https://github.com/owner/repo'} />
        </label>
        <button className="btn btn-primary" type="submit" disabled={ingesting}>{ingesting ? 'Analyzing…' : 'Ingest codebase'}</button>
      </form>
      {ingesting && <div className="hint">Cloning (shallow) and analyzing — nothing in the repository is executed.</div>}
      {error && <div className="error-text">{error}</div>}
      <div className="hint">
        Static analysis only: languages, frameworks, dependencies, test suites, routes and risks such as committed secrets.
        {system?.ingestion?.git_hosts && ` Allowed Git hosts: ${system.ingestion.git_hosts.join(', ')}.`}
      </div>

      {previous.length > 1 && (
        <div className="row small">
          <span className="muted">Previous:</span>
          {previous.slice(0, 6).map((b) => (
            <button key={b.id} type="button" className={`chip ${blueprint?.id === b.id ? 'active' : ''}`} onClick={() => openBlueprint(b.id)}
              title={`${b.source} · ${timeAgo(b.created_at)}`}>{b.name}</button>
          ))}
        </div>
      )}

      {blueprint ? (
        <>
          <div className="approve-row">
            <span className="title">{blueprint.name}</span>
            <span className="small muted cell-wrap">{blueprint.source} · {timeAgo(blueprint.analyzed_at)}</span>
          </div>
          <BlueprintView bp={blueprint} />
        </>
      ) : (
        <div className="empty">No codebase ingested yet. Paste a repository URL{allowLocal ? ' or a folder path' : ''} above.</div>
      )}
    </section>
  );
}
