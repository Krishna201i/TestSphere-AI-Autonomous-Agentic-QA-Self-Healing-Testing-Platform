import React, { useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { getSystem } from '../services/api';

const AI_PROCESSING = {
  cloud: 'This server uses a cloud AI provider. To plan tests and repair broken steps, the structure of the pages you test (element text, labels and selectors) is sent to that provider. Your account details are not.',
  local: 'This server runs its AI model on its own machine; page content is not sent to a third party for AI processing.',
  none: 'This server runs without an AI model; tests are planned by built-in rules and nothing is sent to an AI provider.',
};

const SECTIONS = [
  ['stored', 'What we store'],
  ['where', 'Where it goes'],
  ['rights', 'Your rights'],
  ['contact', 'Contact'],
];

/** What TestSphere stores about you and how to remove it (DPDP Act 2023 / GDPR notice). */
export function PrivacyNotice() {
  const [facts, setFacts] = useState(null);
  useEffect(() => {
    getSystem().then((s) => setFacts(s.privacy || null)).catch(() => setFacts(null));
  }, []);
  const contact = facts?.contact;

  return (
    <>
      <section id="stored" aria-labelledby="stored-h">
        <h2 id="stored-h">What we store</h2>
        <h3>Your account</h3>
        <p>E-mail address, display name and profile picture from your sign-in provider, the profile details you enter, and when you signed up and last signed in.</p>
        <h3>Your work</h3>
        <p>Projects, target URLs, test cases and their results, pipeline runs, security findings, repository blueprints and the audit trail of what you did. Only you can see them.</p>
        <h3>What we do not store</h3>
        <p>Your password (Firebase Authentication handles it), and nothing from the sites you test beyond what the results need.</p>
      </section>

      <section id="where" aria-labelledby="where-h">
        <h2 id="where-h">Where it goes</h2>
        <h3>Storage</h3>
        <p>Google Firebase (Authentication and Cloud Firestore), encrypted at rest and in transit.</p>
        <h3>AI processing</h3>
        <p>{facts ? AI_PROCESSING[facts.ai_processing] || AI_PROCESSING.none : 'Loading…'}</p>
        {facts?.error_reporting && (
          <>
            <h3>Error reports</h3>
            <p>Crashes are reported to Sentry without personal data, so they can be fixed.</p>
          </>
        )}
        <h3>Never</h3>
        <p>Your data is never sold, used for advertising, or shared with anyone else.</p>
      </section>

      <section id="rights" aria-labelledby="rights-h">
        <h2 id="rights-h">Your rights</h2>
        <h3>See it</h3>
        <p>Everything stored about your work is visible in the dashboard; your profile is on the Profile page.</p>
        <h3>Correct it</h3>
        <p>Edit your profile on the Profile page and project settings in Autopilot.</p>
        <h3>Erase it</h3>
        <p>Profile → <b>Delete account</b> removes all of your data and your sign-in account at once. Otherwise data is kept until you delete it.</p>
      </section>

      <section id="contact" aria-labelledby="contact-h">
        <h2 id="contact-h">Contact</h2>
        <p>
          Questions or requests go to{' '}
          {contact
            ? (contact.includes('@') ? <a href={`mailto:${contact}`}>{contact}</a> : <a href={contact} target="_blank" rel="noreferrer">{contact}</a>)
            : 'the operator of this TestSphere server.'}
        </p>
      </section>
    </>
  );
}

function PrivacyDocument({ back }) {
  return (
    <div className="doc-layout">
      <nav className="doc-toc" aria-label="On this page">
        <span className="toc-title">On this page</span>
        {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`} onClick={(e) => {
          // the hash drives routing, so scroll instead of navigating
          e.preventDefault();
          document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
        }}>{label}</a>)}
      </nav>
      <article className="doc">
        {back && (
          <div className="doc-back">
            <button type="button" className="btn btn-sm" onClick={back}><ArrowLeft size={14} /> Back to sign in</button>
          </div>
        )}
        <header>
          <h1>Privacy</h1>
          <p className="doc-lead">What TestSphere stores about you, where it goes, and how to remove it.</p>
          <p className="doc-meta">Applies to this TestSphere server. Written for India's DPDP Act 2023 and the EU GDPR.</p>
        </header>
        <PrivacyNotice />
      </article>
    </div>
  );
}

/** Dashboard page (signed in). */
export default function Privacy() {
  return <PrivacyDocument />;
}

/** Before sign-in: the same notice with a way back to the sign-in screen. */
export function PrivacyStandalone() {
  return <PrivacyDocument back={() => { window.location.hash = ''; }} />;
}
