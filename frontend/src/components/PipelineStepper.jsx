import React from 'react';
import { 
  FileCode2, 
  Play, 
  Stethoscope, 
  Sparkles, 
  CheckCircle, 
  Database 
} from 'lucide-react';

export default function PipelineStepper({ currentStepIndex, onStepClick }) {
  const steps = [
    { key: 'plan', label: '1. PLAN', desc: 'AI Test Planner', icon: FileCode2 },
    { key: 'execute', label: '2. EXECUTE', desc: 'Playwright Engine', icon: Play },
    { key: 'diagnose', label: '3. DIAGNOSE', desc: 'Failure Analyzer', icon: Stethoscope },
    { key: 'heal', label: '4. HEAL', desc: 'Self-Healing Engine', icon: Sparkles },
    { key: 'validate', label: '5. VALIDATE', desc: 'Engine Verification', icon: CheckCircle },
    { key: 'persist', label: '6. PERSIST', desc: 'Database & Metrics', icon: Database },
  ];

  return (
    <div className="stepper-panel card-glass">
      <div className="stepper-header">
        <div className="stepper-title-wrap">
          <span className="section-label">AUTONOMOUS ORCHESTRATION PIPELINE</span>
          <h2 className="section-title">Multi-Agent Self-Healing Execution Lifecycle</h2>
        </div>
        <div className="pipeline-mode-pill">
          <span className="live-pulse" />
          <span>REAL-TIME STREAMING</span>
        </div>
      </div>

      <div className="stepper-container" id="pipeline-stepper">
        {steps.map((s, index) => {
          const Icon = s.icon;
          const isCompleted = index < currentStepIndex;
          const isActive = index === currentStepIndex;
          const isPending = index > currentStepIndex;

          let statusClass = 'pending';
          if (isActive) statusClass = 'active';
          else if (isCompleted) statusClass = 'completed';

          return (
            <React.Fragment key={s.key}>
              <div 
                className={`stepper-node ${statusClass}`}
                onClick={() => onStepClick && onStepClick(index)}
                title={`Click to view details for ${s.label}`}
              >
                <div className="node-icon-circle">
                  <Icon size={18} />
                </div>
                <div className="node-info">
                  <span className="node-label">{s.label}</span>
                  <span className="node-desc">{s.desc}</span>
                </div>
                {isActive && <div className="node-glow-ring" />}
              </div>

              {index < steps.length - 1 && (
                <div className={`stepper-connector ${index < currentStepIndex ? 'completed' : ''}`}>
                  <div className="connector-line" />
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}
