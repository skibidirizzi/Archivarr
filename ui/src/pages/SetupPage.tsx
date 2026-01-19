import { useMemo, useState } from "react";

type BrowseItem = {
  name: string;
  path: string;
  isDir: boolean;
};

type Service = "lidarr" | "sonarr" | "radarr";

type DefaultPingState =
  | { status: "idle" }
  | { status: "testing" }
  | { status: "ok"; baseUrl: string; settingsUrl: string }
  | { status: "error"; message: string };

async function safeReadBody(r: Response): Promise<{ text: string; json: any | null }> {
  const text = await r.text();
  if (!text) return { text: "", json: null };
  try {
    return { text, json: JSON.parse(text) };
  } catch {
    return { text, json: null };
  }
}

function titleCase(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function DirectoryBrowser({
  value,
  onChange,
  onClose,
}: {
  value: string;
  onChange: (path: string) => void;
  onClose: () => void;
}) {
  const [currentPath, setCurrentPath] = useState(value || "");
  const [dirs, setDirs] = useState<BrowseItem[]>([]);
  const [browseError, setBrowseError] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadDirs(path: string) {
    setBrowseError("");
    setLoading(true);
    try {
      const r = await fetch(`/api/v1/browse?path=${encodeURIComponent(path)}`);
      const { json, text } = await safeReadBody(r);
      if (!r.ok) throw new Error((json && (json.detail || json.error)) || text || `HTTP ${r.status}`);
      const data = json;
      setCurrentPath(data.path || path);
      const nextDirs: BrowseItem[] = Array.isArray(data.dirs) ? data.dirs : [];
      setDirs(nextDirs.sort((a, b) => a.name.localeCompare(b.name)));
    } catch (e: any) {
      setBrowseError(e?.message || String(e));
      setDirs([]);
    } finally {
      setLoading(false);
    }
  }

  function selectDir(path: string) {
    onChange(path);
    onClose();
  }

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: "rgba(0,0,0,0.6)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: "#1e1e1e",
          borderRadius: 10,
          padding: 18,
          width: "min(720px, 94vw)",
          maxHeight: "82vh",
          display: "flex",
          flexDirection: "column",
          border: "1px solid #333",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <div style={{ fontSize: 16, fontWeight: 700 }}>Select Folder</div>
          <button className="btn" onClick={onClose} style={{ height: 30 }}>
            Close
          </button>
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <input
            className="input"
            value={currentPath}
            onChange={(e) => setCurrentPath(e.target.value)}
            placeholder="Enter a path (e.g. G:\\Archive\\Music)"
            style={{ flex: 1, width: "auto" }}
          />
          <button className="btn btnPrimary" onClick={() => loadDirs(currentPath)} disabled={loading}>
            {loading ? "Loading" : "Browse"}
          </button>
        </div>

        {browseError && (
          <div style={{ color: "#ff6b6b", fontSize: 12, marginBottom: 8 }}>
            {browseError}
          </div>
        )}

        <div
          style={{
            flex: 1,
            overflowY: "auto",
            backgroundColor: "#141414",
            borderRadius: 8,
            border: "1px solid #2a2a2a",
          }}
        >
          {dirs.length === 0 ? (
            <div style={{ padding: 12, color: "#888", fontSize: 12 }}>No folders loaded.</div>
          ) : (
            dirs.map((d) => (
              <div
                key={d.path}
                onClick={() => selectDir(d.path)}
                style={{
                  padding: "10px 12px",
                  cursor: "pointer",
                  borderBottom: "1px solid #222",
                  color: "#0e9eff",
                }}
              >
                {d.name}
              </div>
            ))
          )}
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button className="btn" onClick={() => selectDir(currentPath)} disabled={!currentPath.trim()}>
             Select This Folder
          </button>
          <div style={{ flex: 1 }} />
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SetupPage({ onSetupComplete }: { onSetupComplete: () => void }) {
  const [step, setStep] = useState<1 | 2>(1);

  const [lidarrEnabled, setLidarrEnabled] = useState(false);
  const [sonarrEnabled, setSonarrEnabled] = useState(false);
  const [radarrEnabled, setRadarrEnabled] = useState(false);

  const [lidarrUrl, setLidarrUrl] = useState("");
  const [lidarrApiKey, setLidarrApiKey] = useState("");
  const [lidarrArchiveRoot, setLidarrArchiveRoot] = useState("");

  const [sonarrUrl, setSonarrUrl] = useState("");
  const [sonarrApiKey, setSonarrApiKey] = useState("");
  const [sonarrArchiveRoot, setSonarrArchiveRoot] = useState("");

  const [radarrUrl, setRadarrUrl] = useState("");
  const [radarrApiKey, setRadarrApiKey] = useState("");
  const [radarrArchiveRoot, setRadarrArchiveRoot] = useState("");

  const [verifySSL, setVerifySSL] = useState(true);
  const [timeoutSec, setTimeoutSec] = useState("30");
  const [sleepBetweenItems, setSleepBetweenItems] = useState("0");
  const [limitItemsPerService, setLimitItemsPerService] = useState("0");
  const [verboseLog, setVerboseLog] = useState(false);
  const [missingPageSize, setMissingPageSize] = useState("2000");
  const [missingMaxPages, setMissingMaxPages] = useState("50");

  const [browsing, setBrowsing] = useState<Service | null>(null);

  const [loading, setLoading] = useState(false);
  const [testingService, setTestingService] = useState<Service | null>(null);
  const [pingingService, setPingingService] = useState<Service | null>(null);
  const [error, setError] = useState("");

  const [defaultPing, setDefaultPing] = useState<Record<Service, DefaultPingState>>({
    lidarr: { status: "idle" },
    sonarr: { status: "idle" },
    radarr: { status: "idle" },
  });

  const [needsAction, setNeedsAction] = useState<null | {
    service: Service;
    path: string;
    message: string;
  }>(null);

  const anyEnabled = lidarrEnabled || sonarrEnabled || radarrEnabled;

  const serviceFields = useMemo(() => {
    return {
      lidarr: {
        enabled: lidarrEnabled,
        url: lidarrUrl,
        apiKey: lidarrApiKey,
        archiveRoot: lidarrArchiveRoot,
        setUrl: setLidarrUrl,
        setApiKey: setLidarrApiKey,
        setArchiveRoot: setLidarrArchiveRoot,
        color: "#0e9eff",
      },
      sonarr: {
        enabled: sonarrEnabled,
        url: sonarrUrl,
        apiKey: sonarrApiKey,
        archiveRoot: sonarrArchiveRoot,
        setUrl: setSonarrUrl,
        setApiKey: setSonarrApiKey,
        setArchiveRoot: setSonarrArchiveRoot,
        color: "#ffc12e",
      },
      radarr: {
        enabled: radarrEnabled,
        url: radarrUrl,
        apiKey: radarrApiKey,
        archiveRoot: radarrArchiveRoot,
        setUrl: setRadarrUrl,
        setApiKey: setRadarrApiKey,
        setArchiveRoot: setRadarrArchiveRoot,
        color: "#e74c3c",
      },
    } as const;
  }, [
    lidarrEnabled,
    lidarrUrl,
    lidarrApiKey,
    lidarrArchiveRoot,
    sonarrEnabled,
    sonarrUrl,
    sonarrApiKey,
    sonarrArchiveRoot,
    radarrEnabled,
    radarrUrl,
    radarrApiKey,
    radarrArchiveRoot,
  ]);

  function buildPayload(createMissingDirs: boolean) {
    const toInt = (s: string, fallback: number) => {
      const n = parseInt(String(s || "").trim(), 10);
      return Number.isFinite(n) ? n : fallback;
    };
    const toFloat = (s: string, fallback: number) => {
      const n = parseFloat(String(s || "").trim());
      return Number.isFinite(n) ? n : fallback;
    };

    return {
      lidarr_url: lidarrEnabled ? lidarrUrl.trim() : "",
      lidarr_api_key: lidarrEnabled ? lidarrApiKey.trim() : "",
      lidarr_archive_root: lidarrEnabled ? lidarrArchiveRoot.trim() : "",

      sonarr_url: sonarrEnabled ? sonarrUrl.trim() : "",
      sonarr_api_key: sonarrEnabled ? sonarrApiKey.trim() : "",
      sonarr_archive_root: sonarrEnabled ? sonarrArchiveRoot.trim() : "",

      radarr_url: radarrEnabled ? radarrUrl.trim() : "",
      radarr_api_key: radarrEnabled ? radarrApiKey.trim() : "",
      radarr_archive_root: radarrEnabled ? radarrArchiveRoot.trim() : "",

      verify_ssl: verifySSL,
      timeout_sec: toInt(timeoutSec, 30),
      sleep_between_items: toFloat(sleepBetweenItems, 0.0),
      limit_items: toInt(limitItemsPerService, 0),
      verbose_log: verboseLog,
      missing_page_size: toInt(missingPageSize, 2000),
      missing_max_pages: toInt(missingMaxPages, 50),

      create_missing_dirs: createMissingDirs,
    };
  }

  async function testConnection(service: Service, baseUrl: string, apiKey: string) {
    const url = baseUrl.trim();
    const key = apiKey.trim();

    if (!url) throw new Error(`${titleCase(service)} URL is required`);
    if (!key) throw new Error(`${titleCase(service)} API key is required`);

    const r = await fetch(`/api/v1/connections/${service}/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: url, api_key: key }),
    });

    const { json, text } = await safeReadBody(r);
    if (!r.ok) {
      const msg = (json && (json.detail || json.error)) || text || `HTTP ${r.status}`;
      throw new Error(msg);
    }

    if (json && json.ok === false) {
      throw new Error(json.error || json.detail || "Connection test failed");
    }
  }

  async function testDefault(service: Service) {
    setError("");
    setNeedsAction(null);
    setPingingService(service);
    setDefaultPing((prev) => ({ ...prev, [service]: { status: "testing" } }));

    try {
      const r = await fetch(`/api/v1/connections/${service}/ping-default`);
      const { json, text } = await safeReadBody(r);
      const data = json ?? {};
      if (!r.ok || data.ok === false) {
        const msg = (data && (data.detail || data.error || data.message)) || text || `HTTP ${r.status}`;
        throw new Error(msg);
      }

      const baseUrl = String(data.base_url || "");
      const settingsUrl = String(data.settings_url || "");
      if (!baseUrl || !settingsUrl) throw new Error("Unexpected ping response");

      // Helpful default: prefill the URL field.
      serviceFields[service].setUrl(baseUrl);
      setDefaultPing((prev) => ({ ...prev, [service]: { status: "ok", baseUrl, settingsUrl } }));
    } catch (e: any) {
      setDefaultPing((prev) => ({
        ...prev,
        [service]: { status: "error", message: e?.message || String(e) },
      }));
    } finally {
      setPingingService(null);
    }
  }

  async function handleStep1Next() {
    setError("");
    setNeedsAction(null);

    const enabledServices: Service[] = [
      ...(lidarrEnabled ? (["lidarr"] as const) : []),
      ...(sonarrEnabled ? (["sonarr"] as const) : []),
      ...(radarrEnabled ? (["radarr"] as const) : []),
    ];

    if (enabledServices.length === 0) {
      setStep(2);
      return;
    }

    for (const s of enabledServices) {
      const f = serviceFields[s];
      if (!f.url.trim()) {
        setError(`${titleCase(s)} URL is required`);
        return;
      }
      if (!f.apiKey.trim()) {
        setError(`${titleCase(s)} API key is required`);
        return;
      }
      if (!f.archiveRoot.trim()) {
        setError(`${titleCase(s)} archive root is required`);
        return;
      }
    }

    try {
      for (const s of enabledServices) {
        setTestingService(s);
        const f = serviceFields[s];
        await testConnection(s, f.url, f.apiKey);
      }
      setStep(2);
    } catch (e: any) {
      setError(`Failed to connect: ${e?.message || String(e)}`);
    } finally {
      setTestingService(null);
    }
  }

  async function submit(createMissingDirs: boolean) {
    setError("");
    setNeedsAction(null);
    setLoading(true);

    try {
      const payload = buildPayload(createMissingDirs);
      const r = await fetch("/api/v1/setup/configure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const { json, text } = await safeReadBody(r);
      const data = json ?? {};

      if (!r.ok) {
        throw new Error((data && (data.error || data.detail)) || text || `HTTP ${r.status}`);
      }

      if (data.ok === false) {
        if (
          data.needsAction === "create_or_select" &&
          (data.service === "lidarr" || data.service === "sonarr" || data.service === "radarr")
        ) {
          // Setup should proactively create missing folders.
          // If the server still reports a missing folder and we haven't tried
          // creation yet, retry once with create_missing_dirs=true.
          if (!createMissingDirs) {
            setLoading(false);
            await submit(true);
            return;
          }

          setNeedsAction({
            service: data.service,
            path: data.path || "",
            message: data.message || "Archive root does not exist",
          });
          return;
        }
        throw new Error(data.error || data.message || "Setup failed");
      }

      onSetupComplete();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  function renderServiceCard(service: Service) {
    const f = serviceFields[service];

    const enabled = f.enabled;
    const setEnabled = (v: boolean) => {
      if (service === "lidarr") setLidarrEnabled(v);
      if (service === "sonarr") setSonarrEnabled(v);
      if (service === "radarr") setRadarrEnabled(v);
    };

    return (
      <div
        key={service}
        style={{
          backgroundColor: "#252525",
          borderRadius: 10,
          padding: 14,
          marginBottom: 14,
          border: enabled ? `1px solid ${f.color}` : "1px solid #444",
        }}
      >
        <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} style={{ width: 18, height: 18 }} />
          <span style={{ fontSize: 16, fontWeight: 700, color: f.color }}>{`Enable ${titleCase(service)}`}</span>
        </label>

        {enabled && (
          <div style={{ marginTop: 12 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
              <div>
                <div style={{ fontSize: 12, color: "#bbb", marginBottom: 4 }}>{titleCase(service)} URL</div>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    className="input"
                    value={f.url}
                    onChange={(e) => f.setUrl(e.target.value)}
                    placeholder={service === "lidarr" ? "http://localhost:8686" : service === "sonarr" ? "http://localhost:8989" : "http://localhost:7878"}
                    style={{ flex: 1, width: "auto" }}
                  />
                  <button className="btn" onClick={() => testDefault(service)} disabled={loading || !!testingService || !!pingingService}>
                    {pingingService === service ? "Pinging" : "Test Default"}
                  </button>
                </div>

                {defaultPing[service].status === "ok" && (
                  <div style={{ marginTop: 6, fontSize: 12, color: "#aaa" }}>
                    Found at <b>{defaultPing[service].baseUrl}</b>. Open{" "}
                    <a href={defaultPing[service].settingsUrl} target="_blank" rel="noreferrer" style={{ color: f.color }}>
                      Settings → General
                    </a>{" "}
                    to copy the API key.
                  </div>
                )}

                {defaultPing[service].status === "error" && (
                  <div style={{ marginTop: 6, fontSize: 12, color: "#ff6b6b" }}>{defaultPing[service].message}</div>
                )}
              </div>

              <div>
                <div style={{ fontSize: 12, color: "#bbb", marginBottom: 4 }}>API Key</div>
                <input className="input" type="password" value={f.apiKey} onChange={(e) => f.setApiKey(e.target.value)} placeholder={`Your ${titleCase(service)} API key`} style={{ width: "100%" }} />
              </div>

              <div>
                <div style={{ fontSize: 12, color: "#bbb", marginBottom: 4 }}>Archive Root</div>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    className="input"
                    value={f.archiveRoot}
                    onChange={(e) => f.setArchiveRoot(e.target.value)}
                    placeholder={service === "lidarr" ? "G:\\Archive\\Music" : service === "sonarr" ? "G:\\Archive\\TV" : "G:\\Archive\\Movies"}
                    style={{ flex: 1, width: "auto" }}
                  />
                  <button className="btn" onClick={() => setBrowsing(service)}>
                    Browse
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ width: "100%", minHeight: "100vh", backgroundColor: "#121212", color: "#fff", padding: "40px 20px" }}>
      <div
        style={{
          maxWidth: 760,
          marginLeft: "auto",
          marginRight: "auto",
          backgroundColor: "#1e1e1e",
          borderRadius: 14,
          padding: 28,
          boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
          border: "1px solid #2a2a2a",
        }}
      >
        <h1 style={{ textAlign: "center", margin: 0 }}>Welcome to Archivarr</h1>
        <p style={{ textAlign: "center", color: "#aaa", marginTop: 8, marginBottom: 22 }}>Start by selecting optional services (Lidarr is not required).</p>

        <div style={{ display: "flex", gap: 8, justifyContent: "center", marginBottom: 22 }}>
          {[1, 2].map((s) => (
            <div key={s} style={{ width: 10, height: 10, borderRadius: 999, backgroundColor: s <= step ? "#0e9eff" : "#444" }} />
          ))}
        </div>

        {step === 1 && (
          <div>
            <h2 style={{ marginTop: 0, marginBottom: 10, color: "#0e9eff" }}>Additional services</h2>
            <p style={{ color: "#aaa", fontSize: 13, marginTop: 0, marginBottom: 18 }}>Enable any services you want. You can skip all services and still finish setup.</p>

            {renderServiceCard("lidarr")}
            {renderServiceCard("sonarr")}
            {renderServiceCard("radarr")}

            {error && <div style={{ color: "#ff6b6b", marginBottom: 12 }}> {error}</div>}

            <div style={{ display: "flex", gap: 10 }}>
              <button
                className="btn"
                onClick={() => {
                  setError("");
                  setNeedsAction(null);
                  setStep(2);
                }}
                disabled={loading || !!testingService || anyEnabled}
                title={anyEnabled ? "Disable all services to use Skip" : "Skip services and continue"}
                style={{ flex: 1, opacity: anyEnabled ? 0.6 : 1 }}
              >
                Skip Services
              </button>
              <button className="btn btnPrimary" onClick={handleStep1Next} disabled={loading || !!testingService} style={{ flex: 1 }}>
                {testingService ? `Testing ${titleCase(testingService)}` : "Next "}
              </button>
            </div>

            {browsing && (
              <DirectoryBrowser value={serviceFields[browsing].archiveRoot} onChange={serviceFields[browsing].setArchiveRoot} onClose={() => setBrowsing(null)} />
            )}
          </div>
        )}

        {step === 2 && (
          <div>
            <h2 style={{ marginTop: 0, marginBottom: 10, color: "#0e9eff" }}>Runtime settings</h2>
            <p style={{ color: "#aaa", fontSize: 13, marginTop: 0, marginBottom: 18 }}>These are safe defaults; you can change them later in Settings.</p>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <div>
                <div style={{ fontSize: 12, color: "#bbb", marginBottom: 4 }}>Timeout (seconds)</div>
                <input className="input" value={timeoutSec} onChange={(e) => setTimeoutSec(e.target.value)} style={{ width: "100%" }} />
              </div>
              <div>
                <div style={{ fontSize: 12, color: "#bbb", marginBottom: 4 }}>Sleep between items (seconds)</div>
                <input className="input" value={sleepBetweenItems} onChange={(e) => setSleepBetweenItems(e.target.value)} style={{ width: "100%" }} />
              </div>
              <div>
                <div style={{ fontSize: 12, color: "#bbb", marginBottom: 4 }}>Limit items per service (0 = no limit)</div>
                <input className="input" value={limitItemsPerService} onChange={(e) => setLimitItemsPerService(e.target.value)} style={{ width: "100%" }} />
              </div>
              <div>
                <div style={{ fontSize: 12, color: "#bbb", marginBottom: 4 }}>Missing page size</div>
                <input className="input" value={missingPageSize} onChange={(e) => setMissingPageSize(e.target.value)} style={{ width: "100%" }} />
              </div>
              <div>
                <div style={{ fontSize: 12, color: "#bbb", marginBottom: 4 }}>Missing max pages</div>
                <input className="input" value={missingMaxPages} onChange={(e) => setMissingMaxPages(e.target.value)} style={{ width: "100%" }} />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, justifyContent: "center" }}>
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input type="checkbox" checked={verifySSL} onChange={(e) => setVerifySSL(e.target.checked)} />
                  <span style={{ fontSize: 13 }}>Verify SSL</span>
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input type="checkbox" checked={verboseLog} onChange={(e) => setVerboseLog(e.target.checked)} />
                  <span style={{ fontSize: 13 }}>Verbose logs</span>
                </label>
              </div>
            </div>

            {needsAction && (
              <div style={{ marginTop: 16, padding: 12, borderRadius: 10, backgroundColor: "rgba(255, 193, 46, 0.12)", border: "1px solid rgba(255, 193, 46, 0.35)" }}>
                <div style={{ fontWeight: 700, marginBottom: 6 }}>Archive folder needs attention</div>
                <div style={{ color: "#ddd", fontSize: 13, marginBottom: 10 }}>
                  {needsAction.message}
                  <div style={{ color: "#aaa", marginTop: 6 }}>{needsAction.path}</div>
                </div>
                <div style={{ display: "flex", gap: 10 }}>
                  <button className="btn" onClick={() => submit(true)} disabled={loading}>
                    Retry Create
                  </button>
                  <button
                    className="btn"
                    onClick={() => {
                      setNeedsAction(null);
                      setBrowsing(needsAction.service);
                    }}
                    disabled={loading}
                  >
                    Choose Different Folder
                  </button>
                </div>
              </div>
            )}

            {error && <div style={{ color: "#ff6b6b", marginTop: 12 }}> {error}</div>}

            <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
              <button
                className="btn"
                onClick={() => {
                  setError("");
                  setNeedsAction(null);
                  setStep(1);
                }}
                disabled={loading}
                style={{ flex: 1 }}
              >
                 Back
              </button>
              <button className="btn btnPrimary" onClick={() => submit(true)} disabled={loading} style={{ flex: 1 }}>
                {loading ? "Saving" : " Complete Setup"}
              </button>
            </div>

            {browsing && (
              <DirectoryBrowser value={serviceFields[browsing].archiveRoot} onChange={serviceFields[browsing].setArchiveRoot} onClose={() => setBrowsing(null)} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
