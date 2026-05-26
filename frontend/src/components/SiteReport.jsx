import { useState, useEffect } from "react";
import { getSites } from "../api";
import AnimatedSelect from "./AnimatedSelect";
import ReportViewer from "./ReportViewer";
import {
  getSiteReport,
  getSiteReportVersions,
  triggerSiteReport,
} from "../api";

export default function SiteReport() {
  const [sites, setSites] = useState([]);
  const [site, setSite] = useState("");

  useEffect(() => {
    getSites().then((s) => {
      setSites(s);
      if (s.length > 0) setSite(s[0].code);
    });
  }, []);

  if (!site) return <div className="loading">Loading sites...</div>;

  return (
    <div>
      <div className="filters">
        <label>
          Site:
          <AnimatedSelect
            options={sites.map((s) => ({
              value: s.code,
              label: `${s.code} — ${s.name}`,
            }))}
            value={site}
            onChange={setSite}
          />
        </label>
      </div>
      <ReportViewer
        key={site}
        fetchReport={(version) => getSiteReport(site, version)}
        fetchVersions={() => getSiteReportVersions(site)}
        triggerGenerate={() => triggerSiteReport(site)}
        generateArgs={[site]}
        label="Site"
      />
    </div>
  );
}
