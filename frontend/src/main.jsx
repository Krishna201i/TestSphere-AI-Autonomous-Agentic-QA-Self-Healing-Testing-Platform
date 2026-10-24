import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import { applyTheme, loadTheme } from './state/theme';
import './styles/theme.css';

applyTheme(loadTheme()); // before the first paint, so a dark theme does not flash light

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
