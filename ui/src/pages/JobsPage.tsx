import { useEffect, useState } from "react";

function fmtSize(bytes: number) {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
}

type Eligible = {
  artistId: number;
  artistName: string;
  path: string;
  size: number;
  albumCount: number;
  targetRoot: string;
  cutoffLabel: string;
  upgradeAllowed: boolean;
};

type RootFolder = {
  id: number;
  path: string;
  isArchiveRoot: boolean;
  freeSpace: number;
};

export function JobsPage() {
  const [eligible, setEligible] = useState<Eligible[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [archiving, setArchiving] = useState<number | null>(null);
  const [rootFolders, setRootFolders] = useState<RootFolder[]>([]);
  const [archiveRootExists, setArchiveRootExists] = useState(true);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const r = await fetch("/api/v1/eligible");
        const j = await r.json();
        if (!r.ok) throw new Error("Failed to load eligible");
        if (alive) setEligible(j);
      } catch (e: any) {
        if (alive) setError(e?.message ?? "Failed to load eligible");
      } finally {
        if (alive) setLoading(false);
      }
    }
    
    async function loadRootFolders() {
      try {
        const r = await fetch("/api/v1/rootfolders");
        const j = await r.json();
        if (Array.isArray(j)) {
          setRootFolders(j);
          const hasArchiveRoot = j.some((rf: RootFolder) => rf.isArchiveRoot);
          setArchiveRootExists(hasArchiveRoot);
        }
      } catch (e) {
        console.error("Failed to load root folders", e);
      }
    }
    
    load();
    loadRootFolders();
    return () => { alive = false; };
  }, []);

  async function handleArchive(artistId: number, artistName: string) {
    let confirmMsg = `Archive "${artistName}"? This will move the artist folder to the archive root.`;
    if (!archiveRootExists) {
      confirmMsg += "\n\n⚠️ The archive root folder does not exist in Lidarr yet. It will be created automatically.";
    }
    if (!window.confirm(confirmMsg)) {
      return;
    }
    setArchiving(artistId);
    try {
      const r = await fetch(`/api/v1/archive/${artistId}`, { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ?? "Archive failed");
      alert(`Successfully archived: ${j.artistName}`);
      setEligible((prev) => prev.filter((e) => e.artistId !== artistId));
      setArchiveRootExists(true);
    } catch (e: any) {
      alert("Archive failed: " + (e as Error).message);
    } finally {
      setArchiving(null);
    }
  }

  async function handleRunNow() {
    if (!window.confirm(`Start archive run for ${eligible.length} eligible artist${eligible.length !== 1 ? "s" : ""}?`)) {
      return;
    }
    try {
      const r = await fetch("/api/v1/run", { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ?? "Run failed");
      alert(`Archive run started! Run ID: ${j.runId}\n\nCheck the Logs page to monitor progress.`);
      setShowPreview(false);
    } catch (e: any) {
      alert("Run failed: " + (e as Error).message);
    }
  }

  return (
    <div className="page">
      <h1>Cutoff Jobs</h1>
      <p className="muted">
        Albums that have reached their cutoff threshold and are eligible to be
        archived.
      </p>

      <div className="panel">
        <div className="panelHeader">
          <div>
            <div className="panelTitle">Filters</div>
            <div className="panelSub">
              Narrow results and preview archive operations
            </div>
          </div>

          <div className="row">
            <input
              className="input"
              placeholder="Search artist or album…"
            />
            <select className="select" defaultValue="all">
              <option value="all">All</option>
              <option value="ready">Ready</option>
              <option value="queued">Queued</option>
              <option value="failed">Failed</option>
            </select>

            <button className="btn" onClick={() => setShowPreview(true)}>Preview Run</button>
            <button className="btn btnPrimary" onClick={handleRunNow}>Run Now</button>
          </div>
        </div>

        {error ? <div className="muted">⛔ {error}</div> : null}
        {loading ? <div className="muted">Loading...</div> : null}
        {!loading && !error && (
          <table className="table" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th>Artist</th>
                <th>Album</th>
                <th>Size</th>
                <th>Current Root</th>
                <th>Target Root</th>
                <th>Cutoff Reason</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {eligible.map((e) => (
                <tr key={e.artistId}>
                  <td>{e.artistName}</td>
                  <td>{e.albumCount} albums</td>
                  <td>{fmtSize(e.size)}</td>
                  <td>{e.path}</td>
                  <td>{e.targetRoot}</td>
                  <td>{e.upgradeAllowed ? "Cutoff Met" : "All Albums Downloaded"}</td>
                  <td>
                    <button
                      className="btn"
                      onClick={() => handleArchive(e.artistId, e.artistName)}
                      disabled={archiving !== null}
                    >
                      {archiving === e.artistId ? "Archiving..." : "Archive"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showPreview && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0, 0, 0, 0.8)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => setShowPreview(false)}
        >
          <div
            style={{
              backgroundColor: "#1e1e1e",
              border: "1px solid #444",
              borderRadius: 8,
              padding: 24,
              width: "75vw",
              height: "75vh",
              overflow: "auto",
              minWidth: 600,
              scrollbarWidth: "none",
              msOverflowStyle: "none",
            } as React.CSSProperties}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h2 style={{ margin: 0 }}>Preview Archive Run</h2>
              <button
                className="btn"
                onClick={() => setShowPreview(false)}
                style={{ fontSize: 20, padding: "4px 12px" }}
              >
                ✕
              </button>
            </div>

            <p className="muted" style={{ marginBottom: 16 }}>
              The following {eligible.length} artist{eligible.length !== 1 ? "s" : ""} will be moved to the archive root:
            </p>

            {eligible.length === 0 ? (
              <div className="muted">No eligible artists to archive.</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", maxHeight: 250, overflow: "hidden" }}>
                <table className="table" style={{ width: "100%", display: "block" }}>
                  <thead style={{ display: "table", width: "100%", tableLayout: "fixed" }}>
                    <tr>
                      <th style={{ width: "25%" }}>Artist</th>
                      <th style={{ width: "10%" }}>Albums</th>
                      <th style={{ width: "12%" }}>Size</th>
                      <th style={{ width: "26.5%" }}>From</th>
                      <th style={{ width: "26.5%" }}>To</th>
                    </tr>
                  </thead>
                </table>
                <div style={{ overflow: "auto", scrollbarWidth: "none", msOverflowStyle: "none" } as React.CSSProperties}>
                  <table className="table" style={{ width: "100%", display: "table", tableLayout: "fixed" }}>
                    <tbody>
                      {eligible.map((e) => (
                        <tr key={e.artistId}>
                          <td style={{ width: "25%" }}>{e.artistName}</td>
                          <td style={{ width: "10%" }}>{e.albumCount}</td>
                          <td style={{ width: "12%" }}>{fmtSize(e.size)}</td>
                          <td style={{ fontSize: 12, color: "#aaa", width: "26.5%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {e.path}
                          </td>
                          <td style={{ fontSize: 12, color: "#aaa", width: "26.5%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {e.targetRoot}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div style={{ marginTop: 20, display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setShowPreview(false)}>
                Close
              </button>
              <button className="btn btnPrimary" onClick={handleRunNow}>
                Run Now
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
