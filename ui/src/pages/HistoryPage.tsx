import { useEffect, useState } from "react";

type RunHistory = {
  id: string;
  status: string;
  created: number;
  type?: string;
  artistName?: string;
  errorMessage?: string;
  result?: {
    moved: number;
    skipped: number;
    errors: number;
    eligibleCount: number;
    artists?: string[];
    errorMessages?: string[];
  };
};

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
  const [runs, setRuns] = useState<RunHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const r = await fetch("/api/v1/history");
        const j = await r.json();
        if (!r.ok) throw new Error("Failed to load history");
        if (alive) setRuns(j);
      } catch (e: any) {
        if (alive) setError(e?.message ?? "Failed to load history");
      } finally {
        if (alive) setLoading(false);
      }
    }
    
    load();
    return () => { alive = false; };
  }, []);

  return (
    <div className="page">
      <h1>Archive History</h1>
      <p className="muted">
        All archive operations and their results
      </p>

      <div className="panel">
        <div className="panelHeader">
          <div>
            <div className="panelTitle">Run History</div>
            <div className="panelSub">
              {runs.length} total run{runs.length !== 1 ? "s" : ""}
            </div>
          </div>
        </div>

        {error ? <div className="muted">⛔ {error}</div> : null}
        {loading ? <div className="muted">Loading...</div> : null}
        {!loading && !error && runs.length === 0 && (
          <div className="muted">No archive runs yet.</div>
        )}
        {!loading && !error && runs.length > 0 && (
          <table className="table" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th>Date & Time</th>
                <th>Artist(s)</th>
                <th>Status</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const artists = run.result?.artists ?? [];
                const artistDisplay = artists.length === 0
                  ? "No artists"
                  : artists.length === 1
                  ? artists[0]
                  : artists.length <= 3
                  ? artists.join(", ")
                  : `${artists.slice(0, 2).join(", ")} and ${artists.length - 2} more`;
                
                const hasErrors = (run.result?.errors ?? 0) > 0 || run.status === "error";
                const errorMessages = run.result?.errorMessages ?? [];
                const errorDisplay = run.status === "error"
                  ? run.errorMessage || "Run failed with an error"
                  : errorMessages.length > 0
                  ? errorMessages.length === 1
                    ? errorMessages[0]
                    : `${errorMessages[0]} and ${errorMessages.length - 1} more error(s)`
                  : "";
                
                return (
                  <tr key={run.id}>
                    <td>
                      <div>{formatTimestamp(run.created)}</div>
                      <div className="muted" style={{ fontSize: '0.85em' }}>
                        {formatDuration(run.created)}
                      </div>
                    </td>
                    <td>
                      {artistDisplay}
                    </td>
                    <td>
                      <span
                        style={{
                          padding: '4px 12px',
                          borderRadius: '4px',
                          fontSize: '0.9em',
                          fontWeight: 500,
                          backgroundColor:
                            run.status === "complete" && (run.result?.errors ?? 0) === 0
                              ? "#16a34a20"
                              : run.status === "error" || (run.result?.errors ?? 0) > 0
                              ? "#dc262620"
                              : run.status === "running"
                              ? "#2563eb20"
                              : "#64748b20",
                          color:
                            run.status === "complete" && (run.result?.errors ?? 0) === 0
                              ? "#16a34a"
                              : run.status === "error" || (run.result?.errors ?? 0) > 0
                              ? "#dc2626"
                              : run.status === "running"
                              ? "#2563eb"
                              : "#64748b",
                        }}
                      >
                        {run.status === "complete" && (run.result?.errors ?? 0) === 0
                          ? "Success"
                          : run.status === "error"
                          ? "Failed"
                          : run.status === "running"
                          ? "Running"
                          : run.status === "queued"
                          ? "Queued"
                          : run.status === "complete" && (run.result?.errors ?? 0) > 0
                          ? "Completed with Errors"
                          : run.status.charAt(0).toUpperCase() + run.status.slice(1)}
                      </span>
                    </td>
                    <td>
                      {hasErrors ? (
                        <span style={{ color: '#dc2626' }}>{errorDisplay}</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
