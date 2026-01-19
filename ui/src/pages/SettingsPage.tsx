import { useEffect, useMemo, useState } from "react";

type Status = { kind: "idle" | "ok" | "err"; msg: string; service?: string };

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
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");

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

  async function createFolder() {
    if (!newFolderName.trim()) {
      setBrowseError("Folder name cannot be empty");
      return;
    }
    
    setBrowseError("");
    try {
      const r = await fetch("/api/v1/browse/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: currentPath,
          name: newFolderName.trim(),
        }),
      });
      
      if (!r.ok) {
        const data = await r.json();
        throw new Error(data.detail || "Failed to create folder");
      }
      
      const data = await r.json();
      setNewFolderName("");
      setCreatingFolder(false);
      // Reload the directory list to show the new folder
      await loadDirs(currentPath);
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
                  onClick={() => setCreatingFolder(!creatingFolder)}
                  style={{ fontSize: 12, padding: "6px 12px", backgroundColor: "#2196F3", color: "white" }}
                >
                  ➕ New Folder
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
          
          {creatingFolder && (
            <div style={{ marginBottom: 12, padding: 10, backgroundColor: "#2a2a2a", borderRadius: 4, border: "1px solid #444" }}>
              <div style={{ fontSize: 12, color: "#aaa", marginBottom: 6 }}>Create new folder in: {currentPath}</div>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  type="text"
                  className="input"
                  placeholder="Folder name"
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  onKeyPress={(e) => {
                    if (e.key === "Enter") {
                      createFolder();
                    }
                  }}
                  style={{ flex: 1, fontSize: 12 }}
                  autoFocus
                />
                <button
                  className="btn"
                  onClick={createFolder}
                  style={{ fontSize: 12, padding: "6px 12px", backgroundColor: "#4CAF50", color: "white" }}
                >
                  Create
                </button>
                <button
                  className="btn"
                  onClick={() => {
                    setCreatingFolder(false);
                    setNewFolderName("");
                    setBrowseError("");
                  }}
                  style={{ fontSize: 12, padding: "6px 12px" }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
          
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
    enabled: { label: "Enable Lidarr", type: "checkbox" },
    url: { label: "Lidarr URL", placeholder: "http://localhost:8686", type: "text" },
    api_key: { label: "API Key", placeholder: "Your Lidarr API key", type: "password" },
    lidarr_archive_root: { label: "Archive Root Directory", placeholder: "C:\\Archive\\Music", type: "browse", required: true },
  },
  Sonarr: {
    enabled: { label: "Enable Sonarr", type: "checkbox" },
    url: { label: "Sonarr URL", placeholder: "http://localhost:8989", type: "text" },
    api_key: { label: "API Key", placeholder: "Your Sonarr API key", type: "password" },
    sonarr_archive_root: { label: "Archive Root Directory", placeholder: "C:\\Archive\\TV", type: "browse", required: false },
  },
  Radarr: {
    enabled: { label: "Enable Radarr", type: "checkbox" },
    url: { label: "Radarr URL", placeholder: "http://localhost:7878", type: "text" },
    api_key: { label: "API Key", placeholder: "Your Radarr API key", type: "password" },
    radarr_archive_root: { label: "Archive Root Directory", placeholder: "C:\\Archive\\Movies", type: "browse", required: false },
  },
  Runtime: {
    verify_ssl: { label: "Verify SSL", type: "checkbox" },
    timeout_sec: { label: "Timeout (seconds)", placeholder: "30", type: "number" },
    sleep_between_items: { label: "Sleep Between Items (seconds)", placeholder: "2", type: "number" },
    limit_items: { label: "Limit Items (per service, 0 = no limit)", placeholder: "0", type: "number" },
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
      // Refresh page to reflect updated configuration
      setTimeout(() => window.location.reload(), 1000);
    } catch {
      setStatus({ kind: "err", msg: "Save failed (network error)." });
    }
  }

  async function testConnection(service: string) {
    setStatus({ kind: "idle", msg: "", service });
    try {
      const baseUrl = getConfigValue(service.charAt(0).toUpperCase() + service.slice(1), "url");
      const apiKey = getConfigValue(service.charAt(0).toUpperCase() + service.slice(1), "api_key");
      const r = await fetch(`/api/v1/connections/${service}/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
      });

      const j = await r.json();
      if (!r.ok) {
        setStatus({ kind: "err", msg: j.detail ?? "Test failed.", service });
        return;
      }
      setStatus({ kind: "ok", msg: `Connected. ${service.charAt(0).toUpperCase() + service.slice(1)} version: ${j.status?.version ?? "unknown"}`, service });
    } catch {
      setStatus({ kind: "err", msg: "Test failed (network error).", service });
    }
  }

  return (
    <div className="page">
      <h1>Settings</h1>
      <p className="muted">Configure integrations and Archivarr behavior.</p>

      {Object.entries(CONFIG_SCHEMA).map(([section, fields]) => {
        // Service colors
        const serviceColors: { [key: string]: string } = {
          Lidarr: "#0e9eff",
          Sonarr: "#ffc12e",
          Radarr: "#e74c3c",
        };
        const serviceColor = serviceColors[section];

        return (
        <div key={section} className="panel" style={{ 
          marginBottom: 20,
          borderLeft: serviceColor ? `4px solid ${serviceColor}` : undefined,
        }}>
          <div className="panelHeader" style={{
            backgroundColor: serviceColor ? `${serviceColor}15` : undefined,
          }}>
            <div>
              <div className="panelTitle" style={{
                color: serviceColor || undefined,
              }}>{section}</div>
              <div className="panelSub">
                {section === "Lidarr" && "Music library archiving"}
                {section === "Sonarr" && "TV series archiving"}
                {section === "Radarr" && "Movie archiving"}
                {section === "Runtime" && "Runtime behavior"}
              </div>
            </div>

            {["Lidarr", "Sonarr", "Radarr"].includes(section) && (
              <button className="btn" onClick={() => testConnection(section.toLowerCase())} disabled={loading}>
                Test Connection
              </button>
            )}
          </div>

          {["Lidarr", "Sonarr", "Radarr"].includes(section) && status.kind !== "idle" && status.service === section.toLowerCase() && (
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
                    key === "enabled" ? (
                      <label style={{
                        position: "relative",
                        display: "inline-block",
                        width: 30,
                        height: 17,
                        cursor: loading ? "not-allowed" : "pointer",
                      }}>
                        <input
                          type="checkbox"
                          checked={["true", "1", "yes", "y"].includes(getConfigValue(section, key).toLowerCase())}
                          onChange={(e) => updateConfig(section, key, e.target.checked ? "true" : "false")}
                          disabled={loading}
                          style={{ opacity: 0, width: 0, height: 0 }}
                        />
                        <span style={{
                          position: "absolute",
                          cursor: loading ? "not-allowed" : "pointer",
                          top: 0,
                          left: 0,
                          right: 0,
                          bottom: 0,
                          backgroundColor: ["true", "1", "yes", "y"].includes(getConfigValue(section, key).toLowerCase()) ? "#4CAF50" : "#ccc",
                          transition: "0.4s",
                          borderRadius: 17,
                        }}>
                          <span style={{
                            position: "absolute",
                            content: "",
                            height: 13,
                            width: 13,
                            left: ["true", "1", "yes", "y"].includes(getConfigValue(section, key).toLowerCase()) ? 15 : 2,
                            bottom: 2,
                            backgroundColor: "white",
                            transition: "0.4s",
                            borderRadius: "50%",
                          }} />
                        </span>
                      </label>
                    ) : (
                      <input
                        type="checkbox"
                        checked={["true", "1", "yes", "y"].includes(getConfigValue(section, key).toLowerCase())}
                        onChange={(e) => updateConfig(section, key, e.target.checked ? "true" : "false")}
                        disabled={loading}
                      />
                    )
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
        );
      })}

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
