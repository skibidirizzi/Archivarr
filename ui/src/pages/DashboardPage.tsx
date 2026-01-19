import { useEffect, useState } from "react";
import { StatCard } from "../components/StatCard";

type ServiceStats = {
  name: string;
  url: string | null;
  configured?: boolean;
  connected: boolean;
  readyToArchive: { count: number; asOf: number | null };
  totalLibrary: { count: number };
  totalWithFiles: { count: number };
  totalTracks?: { count: number };
  totalTracksDownloaded?: { count: number };
  totalEpisodes?: { count: number };
  totalEpisodesDownloaded?: { count: number };
  moves24h: { count: number };
  failures24h: { count: number };
};

type Dashboard = {
  services: Record<string, ServiceStats>;
  lastActivity: { ts: number | null };
};

function fmtMaybe(n: number | null | undefined) {
  return typeof n === "number" ? String(n) : "—";
}

async function readJsonIfPossible(r: Response): Promise<{ json: any | null; text: string }> {
  const text = await r.text();
  if (!text) return { json: null, text: "" };
  try {
    return { json: JSON.parse(text), text };
  } catch {
    return { json: null, text };
  }
}

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [err, setErr] = useState<string>("");

  const configuredServices = data
    ? Object.entries(data.services).filter(([, service]) => (service.configured ?? !!service.url))
    : [];

  useEffect(() => {
    let alive = true;

    async function load() {
      try {
        const r = await fetch("/api/v1/dashboard");
        const { json, text } = await readJsonIfPossible(r);

        if (!r.ok) {
          const detail = json?.detail ?? json?.error ?? json?.message;
          const snippet = (typeof text === "string" ? text : "").trim().slice(0, 200);
          throw new Error(detail ?? (snippet ? `HTTP ${r.status}: ${snippet}` : `HTTP ${r.status}`));
        }

        if (!json) {
          throw new Error("Dashboard returned non-JSON data");
        }

        if (alive) setData(json as Dashboard);
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

      {data ? (
        <>
          {configuredServices.length === 0 ? (
            <div className="panel">
              <div className="panelHeader">
                <div>
                  <div className="panelTitle">No apps configured</div>
                  <div className="panelSub">Add Lidarr/Sonarr/Radarr in Settings to populate the dashboard.</div>
                </div>
              </div>
            </div>
          ) : null}

          {configuredServices.map(([key, service]) => (
            <div key={key} className={`serviceSection ${key === "sonarr" ? "sonarrSection" : ""} ${key === "lidarr" ? "lidarrSection" : ""} ${key === "radarr" ? "radarrSection" : ""}`}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "16px" }}>
                <h2>{service.name}</h2>
                {(() => {
                  const url = service.url;
                  if (!url || !service.connected) return null;
                  return (
                    <button
                      onClick={() => window.open(url, "_blank")}
                      style={{
                        padding: "8px 16px",
                        borderRadius: "6px",
                        border: "1px solid currentColor",
                        background: "transparent",
                        color: "inherit",
                        cursor: "pointer",
                        fontSize: "14px",
                        fontWeight: "500",
                      }}
                    >
                      Open {service.name}
                    </button>
                  );
                })()}
              </div>

              {/* Lidarr-only: eligibility progress bar */}
              {service.name === "Lidarr" && (
                (() => {
                  const total = service.totalLibrary?.count ?? 0;
                  const ready = service.readyToArchive?.count ?? 0;
                  const pct = total > 0 ? Math.round((ready / total) * 100) : 0;
                  const barColor = pct >= 75 ? "#4CAF50" : pct >= 50 ? "#FFC107" : pct >= 25 ? "#FF9800" : "#f44336";
                  return (
                    <div style={{ margin: "12px 0 20px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <div style={{ flex: 1 }}>
                          <div style={{ height: 10, borderRadius: 6, background: "#2a2a2a", overflow: "hidden", boxShadow: "inset 0 0 0 1px #393939" }}>
                            <div style={{ width: `${pct}%`, height: "100%", background: barColor, borderRadius: 6, transition: "width 300ms ease, background 300ms ease" }} />
                          </div>
                        </div>
                        <div style={{ minWidth: 180, fontSize: 12, color: "#aaa" }}>
                          {pct}% eligible ({ready} of {total})
                        </div>
                      </div>
                    </div>
                  );
                })()
              )}

              {/* Sonarr: eligibility progress bar */}
              {service.name === "Sonarr" && (
                (() => {
                  const total = service.totalLibrary?.count ?? 0;
                  const ready = service.readyToArchive?.count ?? 0;
                  const pct = total > 0 ? Math.round((ready / total) * 100) : 0;
                  const barColor = pct >= 75 ? "#4CAF50" : pct >= 50 ? "#FFC107" : pct >= 25 ? "#FF9800" : "#f44336";
                  return (
                    <div style={{ margin: "12px 0 20px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <div style={{ flex: 1 }}>
                          <div style={{ height: 10, borderRadius: 6, background: "#2a2a2a", overflow: "hidden", boxShadow: "inset 0 0 0 1px #393939" }}>
                            <div style={{ width: `${pct}%`, height: "100%", background: barColor, borderRadius: 6, transition: "width 300ms ease, background 300ms ease" }} />
                          </div>
                        </div>
                        <div style={{ minWidth: 200, fontSize: 12, color: "#aaa" }}>
                          {pct}% eligible ({ready} of {total})
                        </div>
                      </div>
                    </div>
                  );
                })()
              )}

              {/* Radarr: eligibility progress bar */}
              {service.name === "Radarr" && (
                (() => {
                  const total = service.totalLibrary?.count ?? 0;
                  const ready = service.readyToArchive?.count ?? 0;
                  const pct = total > 0 ? Math.round((ready / total) * 100) : 0;
                  const barColor = pct >= 75 ? "#4CAF50" : pct >= 50 ? "#FFC107" : pct >= 25 ? "#FF9800" : "#f44336";
                  return (
                    <div style={{ margin: "12px 0 20px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <div style={{ flex: 1 }}>
                          <div style={{ height: 10, borderRadius: 6, background: "#2a2a2a", overflow: "hidden", boxShadow: "inset 0 0 0 1px #393939" }}>
                            <div style={{ width: `${pct}%`, height: "100%", background: barColor, borderRadius: 6, transition: "width 300ms ease, background 300ms ease" }} />
                          </div>
                        </div>
                        <div style={{ minWidth: 180, fontSize: 12, color: "#aaa" }}>
                          {pct}% eligible ({ready} of {total})
                        </div>
                      </div>
                    </div>
                  );
                })()
              )}
              
              {!service.connected && (
                <p className="muted">ℹ️ Not connected. Configure in Settings.</p>
              )}

              <div className="grid">
                <StatCard
                  label={service.name === "Lidarr" ? "Total Albums" : service.name === "Sonarr" ? "Total Series" : "Total Movies"}
                  value={fmtMaybe(service.totalLibrary.count)}
                  hint="Total items in library"
                />
                <StatCard
                  label={service.name === "Lidarr" ? "Albums w/ Files" : service.name === "Sonarr" ? "Series w/ Episodes" : "Movies w/ Files"}
                  value={fmtMaybe(service.totalWithFiles.count)}
                  hint="Items with completed downloads"
                />
                {service.name === "Lidarr" && service.totalTracks && (
                  <StatCard
                    label="Total Tracks"
                    value={fmtMaybe(service.totalTracks.count)}
                    hint="Total tracks across all albums"
                  />
                )}
                {service.name === "Lidarr" && service.totalTracksDownloaded && (
                  <StatCard
                    label="Tracks Downloaded"
                    value={fmtMaybe(service.totalTracksDownloaded.count)}
                    hint="Tracks with files on disk"
                  />
                )}
                {service.name === "Sonarr" && service.totalEpisodes && (
                  <StatCard
                    label="Total Episodes"
                    value={fmtMaybe(service.totalEpisodes.count)}
                    hint="Total episodes across all series"
                  />
                )}
                {service.name === "Sonarr" && service.totalEpisodesDownloaded && (
                  <StatCard
                    label="Episodes Downloaded"
                    value={fmtMaybe(service.totalEpisodesDownloaded.count)}
                    hint="Episodes with files on disk"
                  />
                )}
                <StatCard
                  label="Ready to Archive"
                  value={fmtMaybe(service.readyToArchive.count)}
                  hint={service.name === "Lidarr" ? "Albums that meet cutoff rules" : `${service.name} items that meet cutoff rules`}
                />
                <StatCard
                  label="Moves (24h)"
                  value={fmtMaybe(service.moves24h.count)}
                  hint="Successful moves in last 24 hours"
                />
                <StatCard
                  label="Failures (24h)"
                  value={fmtMaybe(service.failures24h.count)}
                  hint="Failed moves in last 24 hours"
                />
              </div>
            </div>
          ))}
        </>
      ) : null}

    </div>
  );
}
