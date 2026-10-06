import React from 'react';
import { CheckCircle2, Wand2, Timer, Flame, TrendingUp } from 'lucide-react';

export default function MetricsOverview({ stats }) {
  const cards = [
    {
      title: 'Total Test Cases',
      value: stats.totalTests || '1,104',
      subtext: '+12 added today',
      trend: '+4.2%',
      icon: Flame,
      color: 'purple',
    },
    {
      title: 'Pass Rate',
      value: `${stats.passRate || 96.8}%`,
      subtext: '48 passed cleanly',
      trend: '+1.5%',
      icon: CheckCircle2,
      color: 'green',
    },
    {
      title: 'Self-Healed Selectors',
      value: stats.healedCount || '14',
      subtext: '92% AI accuracy score',
      trend: '+8 this week',
      icon: Wand2,
      color: 'cyan',
    },
    {
      title: 'Avg Execution Time',
      value: stats.avgDuration || '1.82s',
      subtext: '3.4x faster than manual',
      trend: '-140ms',
      icon: Timer,
      color: 'indigo',
    },
  ];

  return (
    <div className="metrics-grid">
      {cards.map((c, i) => {
        const Icon = c.icon;
        return (
          <div key={i} className={`metric-card border-${c.color}`}>
            <div className="metric-header">
              <span className="metric-title">{c.title}</span>
              <div className={`metric-icon-wrap icon-${c.color}`}>
                <Icon size={18} />
              </div>
            </div>
            <div className="metric-body">
              <span className="metric-value">{c.value}</span>
              <span className="metric-trend">
                <TrendingUp size={13} />
                {c.trend}
              </span>
            </div>
            <div className="metric-footer">
              <span className="metric-subtext">{c.subtext}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
