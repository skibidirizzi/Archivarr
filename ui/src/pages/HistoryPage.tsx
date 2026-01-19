import { useEffect, useState } from "react";

type ActivityItem = {
  id: string;
  status: string;
  created: number;
  type?: string;
  service?: "lidarr" | "sonarr" | "radarr" | "multi";
  artistName?: string;
  errorMessage?: string;
  result?: {
    moved: number;
    skipped: number;
    errors: number;
    eligibleCount: number;
    ineligibleCount?: number;
    serviceCounts?: { lidarr?: number; sonarr?: number; radarr?: number };
    artists?: string[];
    items?: string[];
    errorMessages?: string[];
  };
};

async function safeReadBody(r: Response): Promise<{ text: string; json: any | null }> {
  const text = await r.text();
  if (!text) return { text: "", json: null };
  try {
    return { text, json: JSON.parse(text) };
  } catch {
    return { text, json: null };
  }
}

function formatTimestamp(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

function formatDuration(created: number) {
  const now = Date.now() / 1000;
  const diff = now - created;
  
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function HistoryPage() {
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const r = await fetch("/api/v1/history");
        const { json, text } = await safeReadBody(r);
        if (!r.ok) throw new Error((json && (json.detail || json.error)) || text || "Failed to load history");
        if (alive) setActivity(Array.isArray(json) ? json : []);
      } catch (e: any) {
        if (alive) setError(e?.message ?? "Failed to load history");
      } finally {
        if (alive) setLoading(false);
      }
    }
    
    load();
    return () => { alive = false; };
  }, []);

  async function clearHistory() {
    if (!activity.length) return;
    const ok = window.confirm("Clear all history (scans + moves)? This cannot be undone.");
    if (!ok) return;

    setClearing(true);
    setError("");
    try {
      const r = await fetch("/api/v1/history/clear", { method: "POST" });
      const { json, text } = await safeReadBody(r);
      const data = json ?? {};
      if (!r.ok || data.ok === false) {
        throw new Error((data && (data.detail || data.error || data.message)) || text || `HTTP ${r.status}`);
      }
      setActivity([]);
    } catch (e: any) {
      setError(e?.message ?? "Failed to clear history");
    } finally {
      setClearing(false);
    }
  }

  return (
    <div className="page">
      <h1>Archive History</h1>
      <p className="muted">
        Scans and move operations and their results
      </p>

      {error ? <div className="muted">⛔ {error}</div> : null}
      {loading ? <div className="muted">Loading...</div> : null}

      {!loading && !error && activity.length === 0 && (
        <div className="muted">No history yet.</div>
      )}

      {!loading && !error && activity.length > 0 && (() => {
        const scans = activity.filter((a) => a.type === "scan");
        const moves = activity.filter((a) => a.type === "move");

        const lidarrMoves = moves.filter((m) => (m.service || "lidarr") === "lidarr");
        const sonarrMoves = moves.filter((m) => m.service === "sonarr");
        const radarrMoves = moves.filter((m) => m.service === "radarr");
        const multiMoves = moves.filter((m) => m.service === "multi");

        const Section = ({
          title,
          color,
          subtitle,
          children,
        }: {
          title: string;
          color: string;
          subtitle: string;
          children: React.ReactNode;
        }) => (
          <div className="panel" style={{ borderLeft: `4px solid ${color}` }}>
            <div className="panelHeader">
              <div>
                <div className="panelTitle" style={{ color }}>{title}</div>
                <div className="panelSub">{subtitle}</div>
              </div>
            </div>
            {children}
          </div>
        );

        const StatusPill = ({ item }: { item: ActivityItem }) => {
          const errorsCount = item.result?.errors ?? 0;
          const isSuccess = item.status === "complete" && errorsCount === 0;
          const isFailure = item.status === "error" || errorsCount > 0;
          const isRunning = item.status === "running";
          const isQueued = item.status === "queued";

          const bg = isSuccess ? "#16a34a20" : isFailure ? "#dc262620" : isRunning ? "#2563eb20" : "#64748b20";
          const fg = isSuccess ? "#16a34a" : isFailure ? "#dc2626" : isRunning ? "#2563eb" : "#64748b";

          const label = isSuccess
            ? "Success"
            : item.status === "error"
            ? "Failed"
            : isRunning
            ? "Running"
            : isQueued
            ? "Queued"
            : item.status === "complete" && errorsCount > 0
            ? "Completed with Errors"
            : item.status.charAt(0).toUpperCase() + item.status.slice(1);

          return (
            <span
              style={{
                padding: "4px 12px",
                borderRadius: "4px",
                fontSize: "0.9em",
                fontWeight: 500,
                backgroundColor: bg,
                color: fg,
              }}
            >
              {label}
            </span>
          );
        };

        const ArchiveTable = ({ rows, label }: { rows: ActivityItem[]; label: string }) => (
          rows.length === 0 ? (
            <div className="muted">No {label} moves yet.</div>
          ) : (
            <table className="table" style={{ width: "100%", textAlign: "center" }}>
              <thead>
                <tr>
                  <th>Date & Time</th>
                  <th>Item(s)</th>
                  <th>Status</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => {
                  const names =
                    item.result?.artists ??
                    item.result?.items ??
                    (item.artistName ? [item.artistName] : []);

                  const itemDisplay = names.length === 0
                    ? "—"
                    : names.length === 1
                    ? names[0]
                    : names.length <= 3
                    ? names.join(", ")
                    : `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`;

                  const hasErrors = (item.result?.errors ?? 0) > 0 || item.status === "error";
                  const errorMessages = item.result?.errorMessages ?? [];
                  const errorDisplay = item.status === "error"
                    ? item.errorMessage || "Move failed with an error"
                    : errorMessages.length > 0
                    ? errorMessages.length === 1
                      ? errorMessages[0]
                      : `${errorMessages[0]} and ${errorMessages.length - 1} more error(s)`
                    : "";

                  return (
                    <tr key={item.id}>
                      <td>
                        <div>{formatTimestamp(item.created)}</div>
                        <div className="muted" style={{ fontSize: "0.85em" }}>{formatDuration(item.created)}</div>
                      </td>
                      <td>{itemDisplay}</td>
                      <td><StatusPill item={item} /></td>
                      <td>
                        {hasErrors ? (
                          <span style={{ color: "#dc2626" }}>{errorDisplay}</span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )
        );

        const ScanTable = ({ rows }: { rows: ActivityItem[] }) => (
          rows.length === 0 ? (
            <div className="muted">No scans yet.</div>
          ) : (
            <table className="table" style={{ width: "100%", textAlign: "center" }}>
              <thead>
                <tr>
                  <th>Date & Time</th>
                  <th>Eligible</th>
                  <th>Ineligible</th>
                  <th>Lidarr</th>
                  <th>Sonarr</th>
                  <th>Radarr</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => {
                  const eligible = item.result?.eligibleCount ?? 0;
                  const ineligible = item.result?.ineligibleCount ?? 0;
                  const counts = item.result?.serviceCounts || {};
                  return (
                    <tr key={item.id}>
                      <td>
                        <div>{formatTimestamp(item.created)}</div>
                        <div className="muted" style={{ fontSize: "0.85em" }}>{formatDuration(item.created)}</div>
                      </td>
                      <td>{eligible}</td>
                      <td>{ineligible}</td>
                      <td>{counts.lidarr ?? 0}</td>
                      <td>{counts.sonarr ?? 0}</td>
                      <td>{counts.radarr ?? 0}</td>
                      <td><StatusPill item={item} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )
        );

        return (
          <>
            <Section title="Scans" color="#8b5cf6" subtitle={`${scans.length} scan${scans.length !== 1 ? "s" : ""}`}>
              <ScanTable rows={scans} />
            </Section>

            <Section title="Multi-service" color="#a78bfa" subtitle={`${multiMoves.length} move${multiMoves.length !== 1 ? "s" : ""}`}>
              <ArchiveTable rows={multiMoves} label="multi-service" />
            </Section>

            <Section title="Lidarr" color="#0e9eff" subtitle={`${lidarrMoves.length} move${lidarrMoves.length !== 1 ? "s" : ""}`}>
              <ArchiveTable rows={lidarrMoves} label="Lidarr" />
            </Section>

            <Section title="Sonarr" color="#ffc12e" subtitle={`${sonarrMoves.length} move${sonarrMoves.length !== 1 ? "s" : ""}`}>
              <ArchiveTable rows={sonarrMoves} label="Sonarr" />
            </Section>

            <Section title="Radarr" color="#e74c3c" subtitle={`${radarrMoves.length} move${radarrMoves.length !== 1 ? "s" : ""}`}>
              <ArchiveTable rows={radarrMoves} label="Radarr" />
            </Section>
          </>
        );
      })()}

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
        <button className="btn" onClick={clearHistory} disabled={loading || clearing || activity.length === 0}>
          {clearing ? "Clearing…" : "Clear history"}
        </button>
      </div>
    </div>
  );
}
