import { useState } from "react";
import styles from "../styles.css";

type BrowseItem = {
  name: string;
  path: string;
  isDir: boolean;
};

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
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setCurrentPath(data.path);
      setDirs(data.dirs.sort((a: BrowseItem, b: BrowseItem) => a.name.localeCompare(b.name)));
    } catch (e: any) {
      setBrowseError((e as Error).message);
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
        backgroundColor: "rgba(0,0,0,0.5)",
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
          borderRadius: "8px",
          padding: "20px",
          maxWidth: "600px",
          width: "90%",
          maxHeight: "80vh",
          display: "flex",
          flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ marginTop: 0, color: "#fff" }}>Select Archive Root</h2>

        <div style={{ marginBottom: "10px", color: "#aaa" }}>
          <input
            type="text"
            value={currentPath}
            onChange={(e) => setCurrentPath(e.target.value)}
            placeholder="Enter path or navigate"
            style={{
              width: "100%",
              padding: "8px",
              backgroundColor: "#2d2d2d",
              color: "#fff",
              border: "1px solid #444",
              borderRadius: "4px",
              boxSizing: "border-box",
            }}
          />
          <button
            onClick={() => loadDirs(currentPath)}
            disabled={loading}
            style={{
              marginTop: "8px",
              padding: "6px 12px",
              backgroundColor: "#0e639c",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
            }}
          >
            {loading ? "Loading..." : "Navigate"}
          </button>
        </div>

        {browseError && <div style={{ color: "#f48771", marginBottom: "10px" }}>{browseError}</div>}

        <div
          style={{
            flex: 1,
            overflowY: "auto",
            backgroundColor: "#252525",
            borderRadius: "4px",
            padding: "10px",
            marginBottom: "10px",
          }}
        >
          {dirs.length === 0 && !browseError ? (
            <div style={{ color: "#888" }}>No directories found or path not loaded</div>
          ) : (
            dirs.map((item, idx) => (
              <div
                key={idx}
                onClick={() => selectDir(item.path)}
                style={{
                  padding: "8px",
                  cursor: "pointer",
                  color: "#0e9eff",
                  borderRadius: "4px",
                }}
                onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.backgroundColor = "#333")}
                onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.backgroundColor = "transparent")}
              >
                {item.name}
              </div>
            ))
          )}
        </div>

        <button
          onClick={onClose}
          style={{
            padding: "8px 16px",
            backgroundColor: "#444",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            cursor: "pointer",
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function SetupPage({ onSetupComplete }: { onSetupComplete: () => void }) {
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [lidarrUrl, setLidarrUrl] = useState("");
  const [lidarrApiKey, setLidarrApiKey] = useState("");
  const [archiveRoot, setArchiveRoot] = useState("");
  const [browsing, setBrowsing] = useState(false);

  async function handleStep1Next() {
    setError("");
    if (!lidarrUrl.trim()) {
      setError("Lidarr URL is required");
      return;
    }
    if (!lidarrApiKey.trim()) {
      setError("Lidarr API Key is required");
      return;
    }

    // Test Lidarr connection
    setLoading(true);
    try {
      const r = await fetch("/api/v1/connections/lidarr/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_url: lidarrUrl, api_key: lidarrApiKey }),
      });
      const data = await r.json();
      if (!data.ok) throw new Error(data.error || "Connection failed");
      setStep(2);
    } catch (e: any) {
      setError(`Failed to connect to Lidarr: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleStep2Next() {
    setError("");
    if (!archiveRoot.trim()) {
      setError("Archive root path is required");
      return;
    }
    setStep(3);
  }

  async function handleFinish() {
    setError("");
    setLoading(true);
    try {
      const r = await fetch("/api/v1/setup/configure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lidarr_url: lidarrUrl,
          lidarr_api_key: lidarrApiKey,
          archive_root: archiveRoot,
          verify_ssl: true,
          timeout_sec: 30,
          limit_artists: 0,
          verbose_log: false,
          missing_page_size: 2000,
          missing_max_pages: 50,
        }),
      });
      const data = await r.json();
      if (!data.ok) throw new Error(data.error || "Setup failed");
      onSetupComplete();
    } catch (e: any) {
      setError(`Setup failed: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        width: "100%",
        height: "100vh",
        backgroundColor: "#121212",
        color: "#fff",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          width: "90%",
          maxWidth: "500px",
          backgroundColor: "#1e1e1e",
          borderRadius: "12px",
          padding: "40px",
          boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
        }}
      >
        <h1 style={{ textAlign: "center", marginBottom: "30px", marginTop: 0 }}>Welcome to Archivarr</h1>

        {/* Step 1: Lidarr Connection */}
        {step === 1 && (
          <div>
            <h2 style={{ marginBottom: "20px", color: "#0e9eff" }}>Step 1: Lidarr Connection</h2>
            <p style={{ color: "#aaa", marginBottom: "20px" }}>
              Enter your Lidarr instance URL and API key to get started.
            </p>

            <div style={{ marginBottom: "15px" }}>
              <label style={{ display: "block", marginBottom: "5px", fontSize: "14px" }}>
                Lidarr URL
              </label>
              <input
                type="text"
                value={lidarrUrl}
                onChange={(e) => setLidarrUrl(e.target.value)}
                placeholder="http://localhost:8686"
                style={{
                  width: "100%",
                  padding: "10px",
                  backgroundColor: "#2d2d2d",
                  color: "#fff",
                  border: "1px solid #444",
                  borderRadius: "4px",
                  boxSizing: "border-box",
                  fontSize: "14px",
                }}
              />
            </div>

            <div style={{ marginBottom: "20px" }}>
              <label style={{ display: "block", marginBottom: "5px", fontSize: "14px" }}>
                API Key
              </label>
              <input
                type="password"
                value={lidarrApiKey}
                onChange={(e) => setLidarrApiKey(e.target.value)}
                placeholder="Your Lidarr API key"
                style={{
                  width: "100%",
                  padding: "10px",
                  backgroundColor: "#2d2d2d",
                  color: "#fff",
                  border: "1px solid #444",
                  borderRadius: "4px",
                  boxSizing: "border-box",
                  fontSize: "14px",
                }}
              />
            </div>

            {error && <div style={{ color: "#f48771", marginBottom: "15px" }}>{error}</div>}

            <button
              onClick={handleStep1Next}
              disabled={loading}
              style={{
                width: "100%",
                padding: "10px",
                backgroundColor: "#0e639c",
                color: "#fff",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "14px",
                opacity: loading ? 0.7 : 1,
              }}
            >
              {loading ? "Testing Connection..." : "Next"}
            </button>
          </div>
        )}

        {/* Step 2: Archive Root */}
        {step === 2 && (
          <div>
            <h2 style={{ marginBottom: "20px", color: "#0e9eff" }}>Step 2: Archive Location</h2>
            <p style={{ color: "#aaa", marginBottom: "20px" }}>
              Select the directory where Archivarr will store archived albums.
            </p>

            <div style={{ marginBottom: "20px" }}>
              <label style={{ display: "block", marginBottom: "5px", fontSize: "14px" }}>
                Archive Root Path
              </label>
              <input
                type="text"
                value={archiveRoot}
                onChange={(e) => setArchiveRoot(e.target.value)}
                placeholder="/path/to/archive"
                style={{
                  width: "100%",
                  padding: "10px",
                  backgroundColor: "#2d2d2d",
                  color: "#fff",
                  border: "1px solid #444",
                  borderRadius: "4px",
                  boxSizing: "border-box",
                  fontSize: "14px",
                  marginBottom: "10px",
                }}
              />
              <button
                onClick={() => setBrowsing(true)}
                style={{
                  width: "100%",
                  padding: "8px",
                  backgroundColor: "#444",
                  color: "#fff",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  fontSize: "14px",
                }}
              >
                Browse
              </button>
            </div>

            {error && <div style={{ color: "#f48771", marginBottom: "15px" }}>{error}</div>}

            <div style={{ display: "flex", gap: "10px" }}>
              <button
                onClick={() => {
                  setError("");
                  setStep(1);
                }}
                style={{
                  flex: 1,
                  padding: "10px",
                  backgroundColor: "#444",
                  color: "#fff",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  fontSize: "14px",
                }}
              >
                Back
              </button>
              <button
                onClick={handleStep2Next}
                style={{
                  flex: 1,
                  padding: "10px",
                  backgroundColor: "#0e639c",
                  color: "#fff",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  fontSize: "14px",
                }}
              >
                Next
              </button>
            </div>

            {browsing && (
              <DirectoryBrowser
                value={archiveRoot}
                onChange={setArchiveRoot}
                onClose={() => setBrowsing(false)}
              />
            )}
          </div>
        )}

        {/* Step 3: Review */}
        {step === 3 && (
          <div>
            <h2 style={{ marginBottom: "20px", color: "#0e9eff" }}>Step 3: Review & Complete</h2>
            <p style={{ color: "#aaa", marginBottom: "20px" }}>
              Review your configuration before completing setup.
            </p>

            <div
              style={{
                backgroundColor: "#252525",
                borderRadius: "4px",
                padding: "15px",
                marginBottom: "20px",
              }}
            >
              <div style={{ marginBottom: "10px" }}>
                <div style={{ color: "#888", fontSize: "12px" }}>Lidarr URL</div>
                <div style={{ color: "#0e9eff" }}>{lidarrUrl}</div>
              </div>
              <div>
                <div style={{ color: "#888", fontSize: "12px" }}>Archive Root</div>
                <div style={{ color: "#0e9eff" }}>{archiveRoot}</div>
              </div>
            </div>

            {error && <div style={{ color: "#f48771", marginBottom: "15px" }}>{error}</div>}

            <div style={{ display: "flex", gap: "10px" }}>
              <button
                onClick={() => {
                  setError("");
                  setStep(2);
                }}
                style={{
                  flex: 1,
                  padding: "10px",
                  backgroundColor: "#444",
                  color: "#fff",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  fontSize: "14px",
                }}
              >
                Back
              </button>
              <button
                onClick={handleFinish}
                disabled={loading}
                style={{
                  flex: 1,
                  padding: "10px",
                  backgroundColor: "#0e639c",
                  color: "#fff",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  fontSize: "14px",
                  opacity: loading ? 0.7 : 1,
                }}
              >
                {loading ? "Setting Up..." : "Complete Setup"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
