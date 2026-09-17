// The full write-up on the river, as a PDF the owner writes directly
// rather than one generated on demand from the readings; see api.js for
// why that changed. Update REPORT_URL and the two labels below when a new
// report is published; the file itself lives in public/reports/.

const REPORT_URL = '/reports/coln-report-august-2026.pdf';
const REPORT_LABEL = 'Project report, August 2026';
const REPORT_FILENAME = 'Coln River Guardians report - August 2026.pdf';

export default function Reports() {
  return (
    <div className="stack">
      <div className="page-header">
        <h1>Reports</h1>
        <p className="lead">The latest full report on the river.</p>
      </div>

      <section className="card stack" aria-labelledby="report-h">
        <div className="cluster" style={{ justifyContent: 'space-between' }}>
          <h2 id="report-h" style={{ margin: 0 }}>{REPORT_LABEL}</h2>
          <div className="cluster">
            <a className="btn btn-primary" href={REPORT_URL} download={REPORT_FILENAME}>
              Download PDF
            </a>
            <a className="btn btn-secondary" href={REPORT_URL} target="_blank" rel="noopener noreferrer">
              Open in a new tab
            </a>
          </div>
        </div>

        <object data={REPORT_URL} type="application/pdf" className="report-viewer" aria-label={REPORT_LABEL}>
          <p className="text-secondary">
            The report can&rsquo;t be shown here.{' '}
            <a href={REPORT_URL}>Open the PDF directly</a> instead.
          </p>
        </object>
      </section>
    </div>
  );
}
