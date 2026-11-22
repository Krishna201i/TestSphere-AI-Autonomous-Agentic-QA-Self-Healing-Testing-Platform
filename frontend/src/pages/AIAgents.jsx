import React, { useMemo } from 'react';
import { ArrowRight, Bot, Code, Shield, Sparkles, Workflow, Wrench } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { loopModel } from '../lib/derive';
import { AGENT_STATE, agentStates } from '../lib/dashboard';

const ICON = { planner: Sparkles, qa: Bot, healer: Wrench, security: Shield, remediation: Code };
const LINK = { planner: ['studio', 'Write a test'], qa: ['runs', 'Test runs'], healer: ['healing', 'Review heals'],
  security: ['security', 'Findings'], remediation: ['remediation', 'Fixes'] };
const PROVIDER = { 'nvidia-gemma': 'NVIDIA Gemma', 'nvidia-nemotron': 'NVIDIA Nemotron', groq: 'Groq', gemini: 'Google Gemini' };

function ModelCard({ llm }) {
  if (!llm) return null;
  if (llm.provider === 'mock') {
    return <p className="hint m-0">No AI model is configured (offline, scripted planner). Set <span className="mono">LLM_PROVIDER</span> on the server to plan, explore and heal with a model.</p>;
  }
  if (llm.provider !== 'chain') {
    return <dl className="kv"><dt>Provider</dt><dd>{llm.provider}</dd><dt>Model</dt><dd className="mono">{llm.model}</dd></dl>;
  }
  return (
    <>
      <p className="hint m-0">Each request goes to the first provider that can answer; one that hits its limit is set aside until it resets.</p>
      <ol className="list">
        {(llm.chain || []).map((c) => (
          <li key={c.name}>
            <b>{PROVIDER[c.name] || c.name}</b> <span className="mono small muted">{c.model}</span>{' '}
            {c.benched_seconds > 0
              ? <span className="pill orange">Resting {Math.ceil(c.benched_seconds / 60)} min</span>
              : <span className="pill green">Ready</span>}
          </li>
        ))}
      </ol>
    </>
  );
}

export default function AIAgents({ onNavigate }) {
  const ws = useWorkspace();
  const loop = useMemo(() => loopModel(ws), [ws]);
  const agents = useMemo(() => agentStates(ws, loop), [ws, loop]);

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>AI Agents</h1>
          <p>The agents that plan, run, heal and secure your tests, and what each is doing right now
            {loop.run ? ` (run #${loop.run.id}, ${loop.active ? 'running' : loop.run.status})` : ''}.</p>
        </div>
        <button type="button" className="btn" onClick={() => onNavigate('visualizer')}><Workflow size={16} /> Pipeline</button>
      </div>

      <div className="grid-main-side">
        <section className="card">
          <div className="card-head"><h3>Agents</h3></div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Agent</th><th>Does</th><th>Now</th><th><span className="visually-hidden">Open</span></th></tr></thead>
              <tbody>
                {agents.map((a) => {
                  const Icon = ICON[a.id] || Bot;
                  const [color, label] = AGENT_STATE[a.state] || AGENT_STATE.idle;
                  const [page, text] = LINK[a.id];
                  return (
                    <tr key={a.id}>
                      <td><span className="row"><Icon size={18} aria-hidden="true" /> <b>{a.name}</b></span></td>
                      <td className="small">{a.about}</td>
                      <td><span className={`pill ${color}`}>{label}</span></td>
                      <td><button type="button" className="btn btn-sm btn-ghost" onClick={() => onNavigate(page)}>{text} <ArrowRight size={14} /></button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
        <div className="stack-lg">
          <section className="card">
            <div className="card-head"><h3>AI model</h3></div>
            {ws.system ? <ModelCard llm={ws.system.llm} /> : <p className="hint m-0">Loading…</p>}
          </section>
          <section className="card">
            <div className="card-head"><h3>Write tests in plain English</h3></div>
            <p className="hint m-0">Describe a test; the planner writes the steps and checks each against your live page.</p>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => onNavigate('studio')}>Open Test Studio</button>
          </section>
        </div>
      </div>
    </div>
  );
}
