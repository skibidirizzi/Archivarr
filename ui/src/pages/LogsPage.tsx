import { useEffect, useState, useRef } from "react";

type LogEntry = string;

export function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [selectedDate, setSelectedDate] = useState<string>(new Date().toISOString().split("T")[0]);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    let alive = true;

    async function loadLogs() {
      try {
        const r = await fetch("/api/v1/logs/current");
        const j = await r.json();
        if (!r.ok) throw new Error("Failed to load logs");
        if (alive) {
          setLogs(j.lines || []);
          setLoading(false);
        }
      } catch (e: any) {
        if (alive) setError(e?.message ?? "Failed to load logs");
      }
    }

    loadLogs();
    const t = setInterval(loadLogs, 1000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  function handleScroll() {
    if (logContainerRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = logContainerRef.current;
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 10;
      setAutoScroll(isAtBottom);
    }
  }

  async function downloadLogs(date: string) {
    try {
      const r = await fetch(`/api/v1/logs/download?date=${date}`);
      if (!r.ok) throw new Error("Download failed");
      const blob = await r.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `archivarr-logs-${date}.txt`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      alert("Failed to download logs: " + (e as Error).message);
    }
  }

  const daysAgo = (n: number) => {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d.toISOString().split("T")[0];
  };

  return (
    <div className="page">
      <h1>Logs</h1>
      <p className="muted">Real-time and historical logs from archival operations.</p>

      <div className="panel">
        <div className="panelHeader">
          <div>
            <div className="panelTitle">Live Logs</div>
            <div className="panelSub">Current run and recent activity</div>
          </div>
        </div>

        {error ? <div style={{ padding: 14 }} className="muted">⛔ {error}</div> : null}
        {loading ? <div style={{ padding: 14 }} className="muted">Loading...</div> : null}
        {!loading && !error && (
          <div
            ref={logContainerRef}
            onScroll={handleScroll}
            style={{
              padding: 14,
              backgroundColor: "#1e1e1e",
              color: "#d4d4d4",
              fontFamily: "monospace",
              fontSize: 12,
              maxHeight: 400,
              overflow: "auto",
              borderRadius: 4,
            }}
          >
            {logs.length === 0 ? (
              <div className="muted">No logs yet. Run a scan to see activity.</div>
            ) : (
              logs.map((message, idx) => (
                <div key={idx} style={{ lineHeight: 1.6 }}>
                  {message}
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <div className="panel" style={{ marginTop: 20 }}>
        <div className="panelHeader">
          <div>
            <div className="panelTitle">Historical Logs</div>
            <div className="panelSub">Download logs from the last 7 days</div>
          </div>
        </div>

        <div style={{ padding: 14, display: "grid", gap: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10 }}>
            {[0, 1, 2, 3, 4, 5, 6].map((day) => {
              const date = daysAgo(day);
              const label = day === 0 ? "Today" : day === 1 ? "Yesterday" : `${day} days ago`;
              return (
                <button
                  key={date}
                  className="btn"
                  onClick={() => downloadLogs(date)}
                  style={{ textAlign: "center" }}
                >
                  {label}
                  <div style={{ fontSize: 11, color: "#888", marginTop: 4 }}>{date}</div>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
