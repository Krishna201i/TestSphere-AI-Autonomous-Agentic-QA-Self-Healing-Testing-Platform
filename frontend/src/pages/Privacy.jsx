import React, { useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { getSystem } from '../services/api';

const AI_PROCESSING = {
  cloud: 'This server uses a cloud AI provider. To plan tests and repair broken steps, the structure of the pages you test (element text, labels and selectors) is sent to that provider. Your account details are not.',
  local: 'This server runs its AI model on its own machine; page content is not sent to a third party for AI processing.',
  none: 'This server runs without an AI model; tests are planned by built-in rules and nothing is sent to an AI provider.',
};

/** What TestSphere stores about you and how to remove it (DPDP Act 2023 / GDPR notice). */
export function PrivacyNotice() {
  const [facts, setFacts] = useState(null);
  useEffect(() => {
    getSystem().then((s) => setFacts(s.privacy || null)).catch(() => setFacts(null));
  }, []);
  const contact = facts?.contact;

  return (
    <div className="privacy">
      <section className="card">
        <div className="card-head"><h3>What is stored</h3></div>
        <dl className="kv">
          <dt>Your account</dt>
          <dd>E-mail address, display name and profile picture from your sign-in provider, the profile details you enter, and when you signed up and last signed in.</dd>
          <dt>Your work</dt>
          <dd>Projects, target URLs, test cases and their results, pipeline runs, security findings, repository blueprints and the audit trail of what you did. Only you can see them.</dd>
          <dt>Not stored</dt>
          <dd>Your password (Firebase Authentication handles it), and nothing from the sites you test beyond what the results need.</dd>
        </dl>
      </section>

      <section className="card">
        <div className="card-head"><h3>Where it goes</h3></div>
        <dl className="kv">
          <dt>Storage</dt>
          <dd>Google Firebase (Authentication and Cloud Firestore), encrypted at rest and in transit.</dd>
          <dt>AI processing</dt>
          <dd>{facts ? AI_PROCESSING[facts.ai_processing] || AI_PROCESSING.none : 'Loading…'}</dd>
          {facts?.error_reporting && (
            <>
              <dt>Error reports</dt>
              <dd>Crashes are reported to Sentry without personal data, so they can be fixed.</dd>
            </>
          )}
          <dt>Never</dt>
          <dd>Sold, used for advertising, or shared with anyone else.</dd>
        </dl>
      </section>

      <section className="card">
        <div className="card-head"><h3>Your rights</h3></div>
        <dl className="kv">
          <dt>See it</dt>
          <dd>Everything stored about your work is visible in the dashboard; your profile is on the Profile page.</dd>
          <dt>Correct it</dt>
          <dd>Edit your profile on the Profile page and project settings in Autopilot.</dd>
          <dt>Erase it</dt>
          <dd>Profile → <b>Delete account</b> removes all of your data and your sign-in account at once. Otherwise data is kept until you delete it.</dd>
          <dt>Contact</dt>
          <dd>
            {contact
              ? (contact.includes('@') ? <a href={`mailto:${contact}`}>{contact}</a> : <a href={contact} target="_blank" rel="noreferrer">{contact}</a>)
              : 'The operator of this TestSphere server.'}
          </dd>
        </dl>
      </section>
    </div>
  );
}

/** Dashboard page (signed in). */
export default function Privacy() {
  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Privacy</h1>
          <p>What TestSphere stores about you, where it goes, and how to remove it.</p>
        </div>
      </div>
      <PrivacyNotice />
    </div>
  );
}

/** Before sign-in: the same notice with a way back to the sign-in screen. */
export function PrivacyStandalone() {
  return (
    <div className="page privacy-standalone">
      <div className="page-title">
        <div>
          <h1>Privacy</h1>
          <p>What TestSphere stores about you, where it goes, and how to remove it.</p>
        </div>
        <button type="button" className="btn" onClick={() => { window.location.hash = ''; }}>
          <ArrowLeft size={16} /> Back to sign in
        </button>
      </div>
      <PrivacyNotice />
    </div>
  );
}
