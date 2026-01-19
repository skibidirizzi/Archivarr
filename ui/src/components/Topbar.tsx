import { useEffect, useState } from "react";
import { StatusChip } from "./StatusChip";

type Chip = { ok: boolean; text: string; url?: string };

type ApiStatus = {
  lidarr?: {
    connected?: boolean;
    version?: string;
    url?: string;
    disabled?: boolean;
  };
  sonarr?: {
    connected?: boolean;
    version?: string;
    url?: string;
    disabled?: boolean;
  };
  radarr?: {
    connected?: boolean;
    version?: string;
    url?: string;
    disabled?: boolean;
  };
  scheduler?: {
    enabled?: boolean;
  };
  lastActivity?: number | null;
};

type Status = {
  lidarr: Chip;
  sonarr: Chip;
  radarr: Chip;
  last_activity: Chip;
};

export function Topbar() {
  const [status, setStatus] = useState<Status>({
    lidarr: { ok: false, text: "Lidarr: —", url: undefined },
    sonarr: { ok: false, text: "Sonarr: —", url: undefined },
    radarr: { ok: false, text: "Radarr: —", url: undefined },
    last_activity: { ok: true, text: "Last Activity: —" },
  });
  const [running, setRunning] = useState(false);
  const [scanStatus, setScanStatus] = useState<'idle' | 'running' | 'complete' | 'error'>('idle');

  const handleScan = async () => {
    setRunning(true);
    try {
      const r = await fetch('/api/v1/scan', { method: 'POST' });
      if (!r.ok) {
        const text = await r.text();
        let detail: string | null = null;
        try {
          const j = text ? JSON.parse(text) : null;
          detail = (j && (j.detail || j.error || j.message)) || null;
        } catch {
          // ignore
        }
        const snippet = (text || '').trim().slice(0, 200);
        throw new Error(detail ?? (snippet ? `HTTP ${r.status}: ${snippet}` : `HTTP ${r.status}`));
      }
      setScanStatus('complete');
      alert('Scan complete. Check the Jobs page to review and execute archive operations.');
      // Refresh page to reflect updated scan results
      window.location.reload();
    } catch (e) {
      alert('Error scanning for eligible items: ' + (e as Error).message);
      setScanStatus('error');
      setRunning(false);
    }
  };

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const r = await fetch("/api/v1/status");
        const j: ApiStatus = await r.json();

        const lidarrOk = !!j?.lidarr?.connected;
        const sonarrOk = !!j?.sonarr?.connected;
        const radarrOk = !!j?.radarr?.connected;

        setStatus({
          lidarr: {
            ok: lidarrOk,
            text: j?.lidarr?.disabled
              ? `Lidarr: Disabled`
              : lidarrOk
              ? `Lidarr: Connected`
              : `Lidarr: Disconnected`,
            url: j?.lidarr?.url,
          },
          sonarr: {
            ok: sonarrOk,
            text: j?.sonarr?.disabled
              ? `Sonarr: Disabled`
              : sonarrOk
              ? `Sonarr: Connected`
              : `Sonarr: Disconnected`,
            url: j?.sonarr?.url,
          },
          radarr: {
            ok: radarrOk,
            text: j?.radarr?.disabled
              ? `Radarr: Disabled`
              : radarrOk
              ? `Radarr: Connected`
              : `Radarr: Disconnected`,
            url: j?.radarr?.url,
          },
          last_activity: {
            ok: true,
            text: j?.lastActivity
              ? `Last Activity: ${new Date(j.lastActivity * 1000).toLocaleString()}`
              : "Last Activity: —",
          },
        });
      } catch {
        setStatus({
          lidarr: { ok: false, text: "Lidarr: Unknown" },
          sonarr: { ok: false, text: "Sonarr: Unknown" },
          radarr: { ok: false, text: "Radarr: Unknown" },
          last_activity: { ok: true, text: "Last Activity: —" },
        });
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="topbar">
      <div className="topbarLeft">
        <div className="title">Archivarr</div>
        <div className="subtitle">Multi-service Archiver</div>
      </div>

      <div className="topbarRight">
        <button className="btn" onClick={handleScan} disabled={running}>
          {running ? 'Scanning...' : 'Scan for Eligible'}
        </button>
        <StatusChip
          ok={scanStatus === 'complete' || scanStatus === 'idle'}
          text={`Scan: ${scanStatus.charAt(0).toUpperCase() + scanStatus.slice(1)}`}
        />
        <StatusChip 
          ok={status.lidarr.ok} 
          text={status.lidarr.text} 
          logo="https://lidarr.audio/img/logo.png"
          href={status.lidarr.url}
        />
        <StatusChip 
          ok={status.sonarr.ok} 
          text={status.sonarr.text} 
          logo="https://sonarr.tv/img/logo.png"
          href={status.sonarr.url}
        />
        <StatusChip 
          ok={status.radarr.ok} 
          text={status.radarr.text} 
          logo="https://radarr.video/img/logo.png"
          href={status.radarr.url}
        />
        <StatusChip ok={status.last_activity.ok} text={status.last_activity.text} />
      </div>
    </header>
  );
}
