import { useEffect, useState } from "react";
import { StatCard } from "../components/StatCard";

type Dashboard = {
  readyToArchive: { count: number; asOf: number | null };
  moves24h: { count: number };
  failures24h: { count: number };
  connectedApps: { count: number };
  lastRun: { ts: number | null };
};

function fmtMaybe(n: number | null | undefined) {
  return typeof n === "number" ? String(n) : "—";
}

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    let alive = true;

    async function load() {
      try {
        const r = await fetch("/api/v1/dashboard");
        const j = await r.json();
        if (!r.ok) throw new Error(j?.detail ?? "Failed to load dashboard");
        if (alive) setData(j);
      } catch (e: any) {
        if (alive) setErr(e?.message ?? "Failed to load dashboard");
      }
    }

    load();
    const t = window.setInterval(load, 15000); // Refresh dashboard every 15 seconds
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  return (
    <div className="page">
      <h1>Dashboard</h1>
      <p className="muted">
        Overview of items that have reached cutoff and are eligible to archive.
      </p>

      {err ? <div className="muted">⛔ {err}</div> : null}

      <div className="grid">
        <StatCard
          label="Ready to Archive"
          value={data ? fmtMaybe(data.readyToArchive.count) : "—"}
          hint="Albums that meet cutoff rules"
        />
        <StatCard
          label="Moves (24h)"
          value={data ? fmtMaybe(data.moves24h.count) : "—"}
          hint="Successful moves in last 24 hours"
        />
        <StatCard
          label="Failures (24h)"
          value={data ? fmtMaybe(data.failures24h.count) : "—"}
          hint="Failed moves in last 24 hours"
        />
        <StatCard
          label="Connected Apps"
          value={data ? fmtMaybe(data.connectedApps.count) : "—"}
          hint="Lidarr and other integrations"
        />
      </div>

      <div className="panel">
        <div className="panelHeader">
          <div>
            <div className="panelTitle">Next steps</div>
            <div className="panelSub">What gets wired up next</div>
          </div>
        </div>

        <ul className="list">
          <li>
            Configure Lidarr connection (URL + API key) under <b>Settings</b>.
          </li>
          <li>
            View albums that meet cutoff rules in <b>Cutoff Jobs</b>.
          </li>
          <li>
            Preview and execute archive moves, then update Lidarr root folders.
          </li>
        </ul>
      </div>
    </div>
  );
}
