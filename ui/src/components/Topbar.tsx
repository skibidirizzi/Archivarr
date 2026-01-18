import { useEffect, useState } from "react";
import { StatusChip } from "./StatusChip";

type Chip = { ok: boolean; text: string };

type ApiStatus = {
  lidarr?: {
    connected?: boolean;
    version?: string;
  };
  scheduler?: {
    enabled?: boolean;
  };
  lastRun?: number | null;
};

type Status = {
  lidarr: Chip;
  last_run: Chip;
};

export function Topbar() {
  const [status, setStatus] = useState<Status>({
    lidarr: { ok: false, text: "Lidarr: —" },
    last_run: { ok: true, text: "Last Run: —" },
  });
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<'idle' | 'queued' | 'running' | 'complete' | 'error'>('idle');

  const handleRun = async () => {
    setRunning(true);
    try {
      const r = await fetch('/api/v1/run', { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      setRunId(j.runId);
      setRunStatus('queued');
    } catch (e) {
      alert('Error starting run: ' + (e as Error).message);
      setRunning(false);
    }
  };

  useEffect(() => {
    if (!runId) return;
    const poll = async () => {
      try {
        const r = await fetch(`/api/v1/run/${runId}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        setRunStatus(data.status);
        if (data.status === 'complete' || data.status === 'error') {
          setRunId(null);
          setRunning(false);
          // Refresh status to update lastRun
          const statusR = await fetch("/api/v1/status");
          const statusJ: ApiStatus = await statusR.json();
          const lidarrOk = !!statusJ?.lidarr?.connected;
          setStatus({
            lidarr: {
              ok: lidarrOk,
              text: lidarrOk
                ? `Lidarr: Connected`
                : `Lidarr: Disconnected`,
            },
            last_run: {
              ok: true,
              text: statusJ?.lastRun
                ? `Last Run: ${new Date(statusJ.lastRun * 1000).toLocaleString()}`
                : "Last Run: —",
            },
          });
        }
      } catch (e) {
        console.error('Error polling run status:', e);
        setRunStatus('error');
        setRunId(null);
      }
    };
    poll();
    const t = setInterval(poll, 2000);
    return () => clearInterval(t);
  }, [runId]);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const r = await fetch("/api/v1/status");
        const j: ApiStatus = await r.json();

        const lidarrOk = !!j?.lidarr?.connected;

        setStatus({
          lidarr: {
            ok: lidarrOk,
            text: lidarrOk
              ? `Lidarr: Connected`
              : `Lidarr: Disconnected`,
          },
          last_run: {
            ok: true,
            text: j?.lastRun
              ? `Last Run: ${new Date(j.lastRun * 1000).toLocaleString()}`
              : "Last Run: —",
          },
        });
      } catch {
        setStatus({
          lidarr: { ok: false, text: "Lidarr: Unknown" },
          last_run: { ok: true, text: "Last Run: —" },
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
        <div className="subtitle">Cutoff Archiver</div>
      </div>

      <div className="topbarRight">
        <button className="btn" onClick={handleRun} disabled={running || runStatus === 'queued' || runStatus === 'running'}>
          {running ? 'Starting...' : 'Run Scan'}
        </button>
        <StatusChip
          ok={runStatus === 'complete' || runStatus === 'idle'}
          text={`Run: ${runStatus.charAt(0).toUpperCase() + runStatus.slice(1)}`}
        />
        <StatusChip ok={status.lidarr.ok} text={status.lidarr.text} />
        <StatusChip ok={status.last_run.ok} text={status.last_run.text} />
      </div>
    </header>
  );
}
