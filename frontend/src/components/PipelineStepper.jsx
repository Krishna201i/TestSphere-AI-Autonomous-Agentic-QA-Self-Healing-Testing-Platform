import React from 'react';
import { 
  FileCode2, 
  Play, 
  Stethoscope, 
  Sparkles, 
  CheckCircle, 
  Database 
} from 'lucide-react';

export default function PipelineStepper({ currentStepIndex = 1, onStepClick }) {
  const steps = [
    { key: 'plan', label: 'PLAN', icon: FileCode2 },
    { key: 'execute', label: 'EXECUTE', icon: Play },
    { key: 'diagnose', label: 'DIAGNOSE', icon: Stethoscope },
    { key: 'heal', label: 'HEAL', icon: Sparkles },
    { key: 'validate', label: 'VALIDATE', icon: CheckCircle },
    { key: 'persist', label: 'PERSIST', icon: Database },
  ];

  return (
    <div className="pipeline-stepper" id="pipeline-stepper">
      {steps.map((s, index) => {
        const Icon = s.icon;
        const isCompleted = index < currentStepIndex;
        const isActive = index === currentStepIndex;

        let nodeClass = 'stepper-node';
        if (isActive) nodeClass += ' active';
        else if (isCompleted) nodeClass += ' completed';

        return (
          <React.Fragment key={s.key}>
            <div 
              className={nodeClass}
              onClick={() => onStepClick && onStepClick(index)}
              title={`Step ${index + 1}: ${s.label}`}
            >
              <div className="stepper-circle">
                <Icon size={20} />
              </div>
              <span className="stepper-label">{s.label}</span>
            </div>

            {index < steps.length - 1 && (
              <div className={`stepper-connector ${index < currentStepIndex ? 'active' : ''}`} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}
