import { useEffect, useRef, useState } from 'react';
import { useApi } from '../lib/useApi.js';
import * as api from '../lib/api.js';
import { LoadingState, ErrorState, EmptyState } from '../components/AsyncState.jsx';
import NativeSelect from '../components/NativeSelect.jsx';
import { formatDate } from '../lib/format.js';

// One kind of report: one per round of testing, covering the whole river.
// The type and audience pickers were removed when the owner cut the other
// report kinds and the parish-council / technical registers — a select
// with one option is a worse way of saying "there is only one".

const SEVERITY_LABEL = { good: 'Good news', watch: 'Worth watching', concern: 'Needs attention' };

function VerificationBadge({ verification }) {
  if (!verification) return null;
  const ok = verification.status === 'verified';
  const problems = [
    ...(verification.unmatched_numbers || []),
    ...(verification.invalid_evidence_ids || []),
    ...(verification.banned_terms || []),
  ];
  return (
    <div className={`verify-badge verify-badge--${ok ? 'ok' : 'warn'}`}>
      <strong>
        {ok
          ? 'Every figure checked against the data'
          : 'Some of this could not be checked automatically'}
      </strong>
      <p>
        {ok
          ? 'Each number in this report was matched back to a reading in the database before it was saved.'
          : `${problems.length} thing(s) in this report could not be matched to the data. Treat those with caution.`}
      </p>
    </div>
  );
}

function RenderedReport({ report }) {
  const body =
    typeof report.report_json === 'string' ? JSON.parse(report.report_json) : report.report_json;
  if (!body) return null;

  return (
    <article className="report stack">
      <header className="stack">
        <h2>{body.headline}</h2>
        <p className="report__meta">
          {report.report_type} report · {report.report_key} · version {report.version} ·
          written {formatDate((report.generated_at || '').slice(0, 10))}
        </p>
        <VerificationBadge verification={report.verification} />
        <p className="lede">{body.summary_plain}</p>
      </header>

      {body.overall_assessment && (
        <p className="report__assessment">
          <strong>Overall: {body.overall_assessment.band}</strong>{' '}
          <span className="muted">({body.overall_assessment.confidence} confidence)</span>
          <br />
          {body.overall_assessment.one_line_reason}
        </p>
      )}

      {(body.key_findings || []).length > 0 && (
        <section>
          <h3>The main things to know</h3>
          <ul className="findings">
            {body.key_findings.map((f, i) => (
              <li key={i} className={`finding finding--${f.severity}`}>
                <span className="finding__tag">{SEVERITY_LABEL[f.severity] || f.severity}</span>
                <strong>{f.title}</strong>
                <p>{f.detail}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {(body.sections || []).map((s, i) => (
        <section key={i}>
          <h3>{s.heading}</h3>
          {String(s.body).split('\n\n').map((para, j) => (
            <p key={j}>{para}</p>
          ))}
        </section>
      ))}

      {body.what_this_means && (
        <section>
          <h3>What this means</h3>
          <p>{body.what_this_means}</p>
        </section>
      )}

      {(body.what_to_watch || []).length > 0 && (
        <section>
          <h3>What to look at next time</h3>
          <ul>
            {body.what_to_watch.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </section>
      )}

      {(body.caveats || []).length > 0 && (
        <section>
          <h3>What this report cannot tell you</h3>
          <ul>
            {body.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </section>
      )}

      {(body.glossary || []).length > 0 && (
        <section>
          <h3>Words used here</h3>
          <dl className="glossary">
            {body.glossary.map((g, i) => (
              <div key={i}>
                <dt>{g.term}</dt>
                <dd>{g.plain_meaning}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <div className="toolbar">
        <button type="button" className="btn" onClick={() => window.print()}>
          Print
        </button>
        <a className="btn" href={api.getReportDownloadUrl(report.id, 'md')} download>
          Download as text
        </a>
        <a className="btn" href={api.getReportDownloadUrl(report.id, 'html')} download>
          Download as a page
        </a>
      </div>
    </article>
  );
}

export default function Reports() {
  const roundsCall = useApi(() => api.getRounds());
  const listCall = useApi(() => api.getReports());

  const [key, setKey] = useState('');
  const [job, setJob] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [error, setError] = useState('');
  const pollRef = useRef(null);

  const rounds = roundsCall.data?.rounds || [];

  // Newest round first: the one somebody is most likely to want.
  const keyOptions = [...rounds]
    .sort((a, b) => b.round - a.round)
    .map((r) => ({
      value: String(r.round),
      label: `Round ${r.round} — ${formatDate(r.start)} to ${formatDate(r.end)}`,
    }));

  const effectiveKey = key || keyOptions[0]?.value || '';

  useEffect(() => () => clearInterval(pollRef.current), []);

  const generate = async () => {
    setError('');
    setViewing(null);
    try {
      const started = await api.generateReport({ type: 'round', key: effectiveKey });
      setJob({ ...started, progress: 0, message: 'Queued' });
      clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.getReportJob(started.job_id);
          setJob(status);
          if (status.state === 'done' || status.state === 'failed') {
            clearInterval(pollRef.current);
            if (status.state === 'done' && status.report_id) {
              const full = await api.getReport(status.report_id);
              setViewing(full);
              listCall.reload();
            }
          }
        } catch {
          /* keep polling; a blip should not kill the run */
        }
      }, 1500);
    } catch (e) {
      setError(e.message);
    }
  };

  const openReport = async (id) => {
    setError('');
    try {
      setViewing(await api.getReport(id));
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="stack">
      <div className="page-header">
        <h1>Reports</h1>
        <p className="lede">
          Every figure in a report is taken from the readings and checked
          against them afterwards, so a report cannot quote a number the data
          does not contain.
        </p>
      </div>

      <section className="card stack" aria-labelledby="ask-h">
        <h2 id="ask-h">Write a report for a round</h2>

        <NativeSelect
          id="report-round"
          label="Which round of testing?"
          value={effectiveKey}
          onChange={setKey}
          options={keyOptions}
        />

        <div className="toolbar">
          <button
            type="button"
            className="btn btn--primary"
            onClick={generate}
            disabled={job?.state === 'queued' || job?.state === 'running'}
          >
            Write this report
          </button>
          <span className="muted">Usually takes under a minute.</span>
        </div>

        {error && <ErrorState message={error} />}

        {job && (job.state === 'queued' || job.state === 'running') && (
          <div className="progress" role="status" aria-live="polite">
            <div className="progress__bar">
              <span style={{ width: `${Math.max(5, job.progress || 0)}%` }} />
            </div>
            <p>{job.message || 'Working…'}</p>
          </div>
        )}
        {job?.state === 'failed' && (
          <ErrorState message={job.error || 'That report could not be written.'} />
        )}
      </section>

      {viewing && <RenderedReport report={viewing} />}

      <section className="card stack" aria-labelledby="written-h">
        <h2 id="written-h">Reports already written</h2>
        {listCall.status === 'loading' && <LoadingState label="Loading reports…" />}
        {listCall.status === 'error' && (
          <ErrorState message={listCall.error} onRetry={listCall.reload} />
        )}
        {listCall.status === 'ready' &&
          ((listCall.data.reports || []).length === 0 ? (
            <EmptyState message="No reports have been written yet." />
          ) : (
            <ul className="report-list">
              {listCall.data.reports.map((r) => (
                <li key={r.id}>
                  <button type="button" className="link-button" onClick={() => openReport(r.id)}>
                    {r.report_type} — {r.report_key}
                  </button>
                  <span className="muted">
                    {' '}
                    v{r.version} · {formatDate((r.generated_at || '').slice(0, 10))}
                  </span>
                </li>
              ))}
            </ul>
          ))}
      </section>
    </div>
  );
}
