import { useEffect, useState } from "react";

function fmtSize(bytes: number) {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
}

type LidarrEligible = {
  artistId: number;
  artistName: string;
  path: string;
  albumCount: number;
  size: number;
};

type SonarrEligible = {
  seriesId: number;
  seriesName: string;
  path: string;
  totalEpisodes: number;
  episodesDownloaded: number;
  size: number;
};

type RadarrEligible = {
  movieId: number;
  movieName: string;
  path: string;
  size: number;
};

type RootFolder = {
  id: number;
  path: string;
  isArchiveRoot: boolean;
  freeSpace: number;
};

export function JobsPage() {
  const [lidarrEligible, setLidarrEligible] = useState<LidarrEligible[]>([]);
  const [sonarrEligible, setSonarrEligible] = useState<SonarrEligible[]>([]);
  const [radarrEligible, setRadarrEligible] = useState<RadarrEligible[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [archiving, setArchiving] = useState<string | null>(null);
  const [rootFolders, setRootFolders] = useState<RootFolder[]>([]);
  const [archiveRootExists, setArchiveRootExists] = useState(true);
  const [showPreview, setShowPreview] = useState(false);

  const totalEligible =
    lidarrEligible.length + sonarrEligible.length + radarrEligible.length;

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const r = await fetch("/api/v1/eligible");
        const j = await r.json();
        if (!r.ok) throw new Error("Failed to load eligible");
        if (alive) {
          const lids: LidarrEligible[] = [];
          const sons: SonarrEligible[] = [];
          const rads: RadarrEligible[] = [];
          for (const it of j as any[]) {
            if (it.service === "lidarr") {
              lids.push({
                artistId: it.artistId,
                artistName: it.artistName,
                path: it.path,
                albumCount: it.albumCount ?? 0,
                size: it.size ?? 0,
              });
            } else if (it.service === "sonarr") {
              sons.push({
                seriesId: it.seriesId,
                seriesName: it.seriesName,
                path: it.path,
                totalEpisodes: it.totalEpisodes ?? 0,
                episodesDownloaded: it.episodesDownloaded ?? 0,
                size: it.size ?? 0,
              });
            } else if (it.service === "radarr") {
              rads.push({
                movieId: it.movieId,
                movieName: it.movieName,
                path: it.path,
                size: it.size ?? 0,
              });
            }
          }
          setLidarrEligible(lids);
          setSonarrEligible(sons);
          setRadarrEligible(rads);
        }
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
    setArchiving(`lidarr:${artistId}`);
    try {
      const r = await fetch(`/api/v1/archive/${artistId}`, { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ?? "Archive failed");
      alert(`Successfully archived: ${j.artistName}`);
      // Refresh page to reflect updated state
      window.location.reload();
    } catch (e: any) {
      alert("Archive failed: " + (e as Error).message);
    } finally {
      setArchiving(null);
    }
  }

  async function handleArchiveSeries(seriesId: number, seriesName: string) {
    if (!window.confirm(`Archive "${seriesName}"? This will change the series root folder to the Sonarr archive root and let Sonarr move files.`)) {
      return;
    }
    setArchiving(`sonarr:${seriesId}`);
    try {
      const r = await fetch(`/api/v1/archive/sonarr/${seriesId}`, { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ?? "Archive failed");
      alert(`Successfully archived: ${j.seriesName ?? seriesName}`);
      // Refresh page to reflect updated state
      window.location.reload();
    } catch (e: any) {
      alert("Archive failed: " + (e as Error).message);
    } finally {
      setArchiving(null);
    }
  }

  async function handleArchiveMovie(movieId: number, movieName: string) {
    if (!window.confirm(`Archive "${movieName}"? This will change the movie root folder to the Radarr archive root and let Radarr move files.`)) {
      return;
    }
    setArchiving(`radarr:${movieId}`);
    try {
      const r = await fetch(`/api/v1/archive/radarr/${movieId}`, { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ?? "Archive failed");
      alert(`Successfully archived: ${j.movieName ?? movieName}`);
      // Refresh page to reflect updated state
      window.location.reload();
    } catch (e: any) {
      alert("Archive failed: " + (e as Error).message);
    } finally {
      setArchiving(null);
    }
  }

  async function handleMoveNow() {
    if (
      !window.confirm(
        `Start moving ${totalEligible} eligible item${totalEligible !== 1 ? "s" : ""} across all services?`
      )
    ) {
      return;
    }
    try {
      const r = await fetch("/api/v1/move", { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ?? "Move request failed");
      alert(`Move job started! Job ID: ${j.moveId}\n\nCheck the Logs page to monitor progress.`);
      setShowPreview(false);
    } catch (e: any) {
      alert("Move request failed: " + (e as Error).message);
    }
  }

  return (
    <div className="page">
      <h1>Archive Jobs</h1>
      <p className="muted">
        Items that have reached their cutoff threshold and are eligible to be archived.
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
              placeholder="Search…"
            />
            <select className="select" defaultValue="all">
              <option value="all">All</option>
              <option value="ready">Ready</option>
              <option value="queued">Queued</option>
              <option value="failed">Failed</option>
            </select>

            <button className="btn" onClick={() => setShowPreview(true)}>Preview Moves</button>
            <button className="btn btnPrimary" onClick={handleMoveNow}>Move Now</button>
          </div>
        </div>

        {error ? <div className="muted">⛔ {error}</div> : null}
        {loading ? <div className="muted">Loading...</div> : null}
        {!loading && !error && (
          <>
            {/* Lidarr Section */}
            <div className="serviceSection lidarrSection" style={{ marginBottom: 24 }}>
              <h2 style={{ marginTop: 0 }}>Lidarr</h2>
              <table className="table" style={{ width: '100%' }}>
                <thead>
                  <tr>
                    <th>Artist</th>
                    <th>Albums</th>
                    <th>Size</th>
                    <th>Current Path</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {lidarrEligible.map((e) => (
                    <tr key={e.artistId}>
                      <td>{e.artistName || "Unknown Artist"}</td>
                      <td>{e.albumCount || 0}</td>
                      <td>{fmtSize(e.size || 0)}</td>
                      <td>{e.path || "N/A"}</td>
                      <td>
                        <button
                          className="btn"
                          onClick={() => handleArchive(e.artistId, e.artistName)}
                          disabled={archiving !== null}
                        >
                          {archiving === `lidarr:${e.artistId}` ? "Archiving..." : "Archive"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Sonarr Section */}
            <div className="serviceSection sonarrSection">
              <h2 style={{ marginTop: 0 }}>Sonarr</h2>
              <table className="table" style={{ width: '100%' }}>
                <thead>
                  <tr>
                    <th>Series</th>
                    <th>Episodes</th>
                    <th>Size</th>
                    <th>Current Path</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sonarrEligible.map((s) => (
                    <tr key={s.seriesId}>
                      <td>{s.seriesName || "Unknown Series"}</td>
                      <td>{s.episodesDownloaded}/{s.totalEpisodes}</td>
                      <td>{fmtSize(s.size || 0)}</td>
                      <td>{s.path || "N/A"}</td>
                      <td>
                        <button
                          className="btn"
                          onClick={() => handleArchiveSeries(s.seriesId, s.seriesName)}
                          disabled={archiving !== null}
                        >
                          {archiving === `sonarr:${s.seriesId}` ? "Archiving..." : "Archive"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Radarr Section */}
            <div className="serviceSection radarrSection" style={{ marginTop: 24 }}>
              <h2 style={{ marginTop: 0 }}>Radarr</h2>
              <table className="table" style={{ width: '100%' }}>
                <thead>
                  <tr>
                    <th>Movie</th>
                    <th>Size</th>
                    <th>Current Path</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {radarrEligible.map((m) => (
                    <tr key={m.movieId}>
                      <td>{m.movieName || "Unknown Movie"}</td>
                      <td>{fmtSize(m.size || 0)}</td>
                      <td>{m.path || "N/A"}</td>
                      <td>
                        <button
                          className="btn"
                          onClick={() => handleArchiveMovie(m.movieId, m.movieName)}
                          disabled={archiving !== null}
                        >
                          {archiving === `radarr:${m.movieId}` ? "Archiving..." : "Archive"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
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
              <h2 style={{ margin: 0 }}>Preview Moves</h2>
              <button
                className="btn"
                onClick={() => setShowPreview(false)}
                style={{ fontSize: 20, padding: "4px 12px" }}
              >
                ✕
              </button>
            </div>

            <p className="muted" style={{ marginBottom: 16 }}>
              The following {totalEligible} item{totalEligible !== 1 ? "s" : ""} will be archived.
            </p>

            <p className="muted" style={{ marginBottom: 16 }}>
              Lidarr/Sonarr/Radarr update the root folder and let the service move files.
            </p>

            {totalEligible === 0 ? (
              <div className="muted">No eligible items to archive.</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                {/* Lidarr */}
                <div>
                  <div className="muted" style={{ marginBottom: 8 }}>
                    Lidarr: {lidarrEligible.length} artist{lidarrEligible.length !== 1 ? "s" : ""}
                  </div>
                  {lidarrEligible.length === 0 ? (
                    <div className="muted">No eligible Lidarr artists.</div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", maxHeight: 220, overflow: "hidden" }}>
                      <table className="table" style={{ width: "100%", display: "block" }}>
                        <thead style={{ display: "table", width: "100%", tableLayout: "fixed" }}>
                          <tr>
                            <th style={{ width: "25%" }}>Artist</th>
                            <th style={{ width: "10%" }}>Albums</th>
                            <th style={{ width: "12%" }}>Size</th>
                            <th style={{ width: "51%" }}>From</th>
                          </tr>
                        </thead>
                      </table>
                      <div
                        style={{ overflow: "auto", scrollbarWidth: "none", msOverflowStyle: "none" } as React.CSSProperties}
                      >
                        <table className="table" style={{ width: "100%", display: "table", tableLayout: "fixed" }}>
                          <tbody>
                            {lidarrEligible.map((e) => (
                              <tr key={e.artistId}>
                                <td style={{ width: "25%" }}>{e.artistName}</td>
                                <td style={{ width: "10%" }}>{e.albumCount}</td>
                                <td style={{ width: "12%" }}>{fmtSize(e.size)}</td>
                                <td
                                  style={{
                                    fontSize: 12,
                                    color: "#aaa",
                                    width: "51%",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                  }}
                                >
                                  {e.path}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>

                {/* Sonarr */}
                <div>
                  <div className="muted" style={{ marginBottom: 8 }}>
                    Sonarr: {sonarrEligible.length} series
                  </div>
                  {sonarrEligible.length === 0 ? (
                    <div className="muted">No eligible Sonarr series.</div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", maxHeight: 220, overflow: "hidden" }}>
                      <table className="table" style={{ width: "100%", display: "block" }}>
                        <thead style={{ display: "table", width: "100%", tableLayout: "fixed" }}>
                          <tr>
                            <th style={{ width: "30%" }}>Series</th>
                            <th style={{ width: "16%" }}>Episodes</th>
                            <th style={{ width: "12%" }}>Size</th>
                            <th style={{ width: "40%" }}>From</th>
                          </tr>
                        </thead>
                      </table>
                      <div
                        style={{ overflow: "auto", scrollbarWidth: "none", msOverflowStyle: "none" } as React.CSSProperties}
                      >
                        <table className="table" style={{ width: "100%", display: "table", tableLayout: "fixed" }}>
                          <tbody>
                            {sonarrEligible.map((s) => (
                              <tr key={s.seriesId}>
                                <td style={{ width: "30%" }}>{s.seriesName}</td>
                                <td style={{ width: "16%" }}>
                                  {s.episodesDownloaded}/{s.totalEpisodes}
                                </td>
                                <td style={{ width: "12%" }}>{fmtSize(s.size)}</td>
                                <td
                                  style={{
                                    fontSize: 12,
                                    color: "#aaa",
                                    width: "40%",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                  }}
                                >
                                  {s.path}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>

                {/* Radarr */}
                <div>
                  <div className="muted" style={{ marginBottom: 8 }}>
                    Radarr: {radarrEligible.length} movie{radarrEligible.length !== 1 ? "s" : ""}
                  </div>
                  {radarrEligible.length === 0 ? (
                    <div className="muted">No eligible Radarr movies.</div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", maxHeight: 220, overflow: "hidden" }}>
                      <table className="table" style={{ width: "100%", display: "block" }}>
                        <thead style={{ display: "table", width: "100%", tableLayout: "fixed" }}>
                          <tr>
                            <th style={{ width: "30%" }}>Movie</th>
                            <th style={{ width: "12%" }}>Size</th>
                            <th style={{ width: "56%" }}>From</th>
                          </tr>
                        </thead>
                      </table>
                      <div
                        style={{ overflow: "auto", scrollbarWidth: "none", msOverflowStyle: "none" } as React.CSSProperties}
                      >
                        <table className="table" style={{ width: "100%", display: "table", tableLayout: "fixed" }}>
                          <tbody>
                            {radarrEligible.map((m) => (
                              <tr key={m.movieId}>
                                <td style={{ width: "30%" }}>{m.movieName}</td>
                                <td style={{ width: "12%" }}>{fmtSize(m.size)}</td>
                                <td
                                  style={{
                                    fontSize: 12,
                                    color: "#aaa",
                                    width: "56%",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                  }}
                                >
                                  {m.path}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            <div style={{ marginTop: 20, display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setShowPreview(false)}>
                Close
              </button>
              <button className="btn btnPrimary" onClick={handleRunNow}>
                Move Now
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
