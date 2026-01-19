import { StatCard } from "../components/StatCard";

export function DashboardPage() {
  return (
    <div className="page">
      <h1>Dashboard</h1>
      <p className="muted">
        Overview of items that have reached cutoff and are eligible to archive.
      </p>

      <div className="grid">
        <StatCard label="Ready to Archive" value="—" hint="Albums that meet cutoff rules" />
        <StatCard label="Moves (24h)" value="—" hint="Successful moves in last 24 hours" />
        <StatCard label="Failures (24h)" value="—" hint="Failed moves in last 24 hours" />
        <StatCard label="Connected Apps" value="—" hint="Lidarr / others status" />
      </div>

      <div className="panel">
        <div className="panelHeader">
          <div>
            <div className="panelTitle">Next steps</div>
            <div className="panelSub">What we wire up after the shell</div>
          </div>
        </div>

        <ul className="list">
          <li>Connections page: add Lidarr URL + API key + “Test”.</li>
          <li>Jobs table: show albums that meet cutoff + preview move plan.</li>
          <li>Run: execute move + update root folder in Lidarr.</li>
        </ul>
      </div>
    </div>
  );
}
