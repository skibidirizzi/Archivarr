import { useEffect, useMemo, useState } from "react";

type Status = { kind: "idle" | "ok" | "err"; msg: string };

type Config = {
  [section: string]: {
    [key: string]: string;
  };
};

type BrowseItem = {
  name: string;
  path: string;
  isDir: boolean;
};

function DirectoryBrowser({
  value,
  onChange,
}: {
  value: string;
  onChange: (path: string) => void;
}) {
  const [browsing, setBrowsing] = useState(false);
  const [currentPath, setCurrentPath] = useState(value || "");
  const [dirs, setDirs] = useState<BrowseItem[]>([]);
  const [browseError, setBrowseError] = useState("");

  useEffect(() => {
    if (browsing && !currentPath) {
      // Load initial directory list
      loadDirs("");
    }
  }, [browsing, currentPath]);

  async function loadDirs(path: string) {
    setBrowseError("");
    try {
      const r = await fetch(`/api/v1/browse?path=${encodeURIComponent(path)}`);
      const data = await r.json();
      setCurrentPath(data.path);
      setDirs(data.dirs.sort((a: BrowseItem, b: BrowseItem) => a.name.localeCompare(b.name)));
    } catch (e: any) {
      setBrowseError((e as Error).message);
    }
  }

  function selectDir(path: string) {
    onChange(path);
    setBrowsing(false);
    setCurrentPath("");
    setDirs([]);
  }

  return (
    <div>
      <button
        className="btn"
        onClick={() => {
          if (browsing) {
            setBrowsing(false);
            setCurrentPath("");
            setDirs([]);
          } else {
            setBrowsing(true);
          }
        }}
        style={{ marginBottom: 8 }}
      >
        {browsing ? "Close" : "📁 Browse"}
      </button>

      {browsing && (
        <div
          style={{
            marginTop: 8,
            padding: 12,
            border: "1px solid #444",
            borderRadius: 4,
            backgroundColor: "#1e1e1e",
            maxHeight: 400,
            overflowY: "auto",
            width: "100%",
            maxWidth: "none",
            overflowY: "auto",
          }}
        >
          {browseError && (
            <div style={{ color: "#ff6b6b", marginBottom: 8 }}>❌ {browseError}</div>
          )}
          <div style={{ fontSize: 12, color: "#aaa", marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span>
              Current: <code style={{ color: "#bbb", backgroundColor: "#2a2a2a", padding: "2px 6px", borderRadius: 3 }}>{currentPath || "/"}</code>
            </span>
            {currentPath && (
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  className="btn"
                  onClick={() => selectDir(currentPath)}
                  style={{ fontSize: 12, padding: "6px 12px", backgroundColor: "#4CAF50", color: "white" }}
                >
                  ✓ Select This Folder
                </button>
                <button
                  className="btn"
                  onClick={() => {
                    const parentPath = currentPath.split(/[/\\]/).slice(0, -1).join("/") || "";
                    loadDirs(parentPath);
                  }}
                  style={{ fontSize: 12, padding: "6px 12px" }}
                >
                  ⬆️ Up
                </button>
              </div>
            )}
          </div>
          {dirs.length === 0 && !browseError && (
            <div className="muted" style={{ fontSize: 12 }}>
              Loading...
            </div>
          )}
          {dirs.map((dir) => (
            <div
              key={dir.path}
              style={{
                padding: 10,
                marginBottom: 6,
                backgroundColor: "#2a2a2a",
                border: "1px solid #444",
                borderRadius: 3,
                cursor: "pointer",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                              transition: "background-color 0.2s",
              }}
              onClick={() => loadDirs(dir.path)}
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "#333")}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "#2a2a2a")}
            >
              <span style={{ fontSize: 14, color: "#e0e0e0", flex: 1 }}>📁 {dir.name}</span>
              <button
                className="btn"
                onClick={(e) => {
                  e.stopPropagation();
                  selectDir(dir.path);
                }}
                style={{ fontSize: 12, padding: "6px 12px", marginLeft: 8 }}
              >
                Select
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const CONFIG_SCHEMA: { [section: string]: { [key: string]: any } } = {
  Lidarr: {
    url: { label: "Lidarr URL", placeholder: "http://localhost:8686", type: "text" },
    api_key: { label: "API Key", placeholder: "Your Lidarr API key", type: "password" },
    verify_ssl: { label: "Verify SSL", type: "checkbox" },
    timeout_sec: { label: "Timeout (seconds)", placeholder: "30", type: "number" },
  },
  Archive: {
    archive_root: { label: "Archive Root Directory", placeholder: "/mnt/archive", type: "browse" },
  },
  Runtime: {
    sleep_between_artists: { label: "Sleep Between Artists (seconds)", placeholder: "2", type: "number" },
    limit_artists: { label: "Limit Artists (0 = no limit)", placeholder: "0", type: "number" },
    verbose_log: { label: "Verbose Logging", type: "checkbox" },
    missing_page_size: { label: "Missing Page Size", placeholder: "10", type: "number" },
    missing_max_pages: { label: "Missing Max Pages", placeholder: "5", type: "number" },
  },
};

export function SettingsPage() {
  const [config, setConfig] = useState<Config>({});
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<Status>({ kind: "idle", msg: "" });

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/v1/config");
        const j = await r.json();
        setConfig(j.config ?? {});
      } catch {
        setStatus({ kind: "err", msg: "Failed to load settings." });
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  function updateConfig(section: string, key: string, value: string) {
    setConfig((prev) => ({
      ...prev,
      [section]: { ...prev[section], [key]: value },
    }));
  }

  function getConfigValue(section: string, key: string): string {
    return config[section]?.[key] ?? "";
  }

  async function saveSettings() {
    setStatus({ kind: "idle", msg: "" });
    try {
      const r = await fetch("/api/v1/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });

      const j = await r.json();
      if (!r.ok) {
        setStatus({ kind: "err", msg: j.detail ?? "Save failed." });
        return;
      }
      setStatus({ kind: "ok", msg: "Settings saved to config.ini" });
    } catch {
      setStatus({ kind: "err", msg: "Save failed (network error)." });
    }
  }

  async function testLidarrConnection() {
    setStatus({ kind: "idle", msg: "" });
    try {
      const baseUrl = getConfigValue("Lidarr", "url");
      const apiKey = getConfigValue("Lidarr", "api_key");
      const r = await fetch("/api/v1/connections/lidarr/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
      });

      const j = await r.json();
      if (!r.ok) {
        setStatus({ kind: "err", msg: j.detail ?? "Test failed." });
        return;
      }
      setStatus({ kind: "ok", msg: `Connected. Lidarr version: ${j.status?.version ?? "unknown"}` });
    } catch {
      setStatus({ kind: "err", msg: "Test failed (network error)." });
    }
  }

  return (
    <div className="page">
      <h1>Settings</h1>
      <p className="muted">Configure integrations and Archivarr behavior.</p>

      {Object.entries(CONFIG_SCHEMA).map(([section, fields]) => (
        <div key={section} className="panel" style={{ marginBottom: 20 }}>
          <div className="panelHeader">
            <div>
              <div className="panelTitle">{section}</div>
              <div className="panelSub">
                {section === "Lidarr" && "Connection settings"}
                {section === "Archive" && "Archive destination"}
                {section === "Runtime" && "Runtime behavior"}
              </div>
            </div>

            {section === "Lidarr" && (
              <button className="btn" onClick={testLidarrConnection} disabled={loading}>
                Test Connection
              </button>
            )}
          </div>

          {section === "Lidarr" && status.kind !== "idle" && (
            <div style={{ padding: "0 14px 14px 14px" }}>
              <div className="muted" style={{ padding: "8px 12px", backgroundColor: status.kind === "ok" ? "#d4edda" : "#f8d7da", color: status.kind === "ok" ? "#155724" : "#721c24", borderRadius: 4 }}>
                {status.kind === "ok" ? "✅ " : "❌ "}{status.msg}
              </div>
            </div>
          )}

          <div style={{ padding: 14 }}>
            <div style={{ display: "grid", gap: 16 }}>
              {Object.entries(fields).map(([key, field]: any) => (
                <div key={key} style={{ display: "grid", gap: 6 }}>
                  <div className="muted" style={{ fontSize: 12 }}>{field.label}</div>
                  {field.type === "text" || field.type === "password" || field.type === "number" ? (
                    <input
                      type={field.type}
                      className="input"
                      style={{ width: "100%", maxWidth: 400 }}
                      placeholder={field.placeholder}
                      value={getConfigValue(section, key)}
                      onChange={(e) => updateConfig(section, key, e.target.value)}
                      disabled={loading}
                    />
                  ) : field.type === "browse" ? (
                    <>
                      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                        <input
                          type="text"
                          className="input"
                          style={{ flex: 1, maxWidth: 400 }}
                          placeholder={field.placeholder}
                          value={getConfigValue(section, key)}
                          onChange={(e) => updateConfig(section, key, e.target.value)}
                          disabled={loading}
                        />
                        <DirectoryBrowser
                          value={getConfigValue(section, key)}
                          onChange={(path) => updateConfig(section, key, path)}
                        />
                      </div>
                    </>
                  ) : field.type === "checkbox" ? (
                    <input
                      type="checkbox"
                      checked={["true", "1", "yes", "y"].includes(getConfigValue(section, key).toLowerCase())}
                      onChange={(e) => updateConfig(section, key, e.target.checked ? "true" : "false")}
                      disabled={loading}
                    />
                  ) : field.type === "select" ? (
                    <select
                      className="select"
                      value={getConfigValue(section, key)}
                      onChange={(e) => updateConfig(section, key, e.target.value)}
                      disabled={loading}
                    >
                      {field.options?.map((opt: string) => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </select>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        </div>
      ))}

      <div className="panel">
        <div style={{ padding: 14, display: "flex", gap: 10 }}>
          <button className="btn btnPrimary" onClick={saveSettings} disabled={loading}>
            Save All Settings
          </button>
        </div>
      </div>
    </div>
  );
}
