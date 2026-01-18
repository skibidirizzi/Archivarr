import { Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { AppShell } from "./components/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { JobsPage } from "./pages/JobsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { LogsPage } from "./pages/LogsPage";
import { HistoryPage } from "./pages/HistoryPage";
import SetupPage from "./pages/SetupPage";


export default function App() {
  const [configured, setConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    checkSetupStatus();
  }, []);

  async function checkSetupStatus() {
    try {
      const r = await fetch("/api/v1/setup/status");
      const data = await r.json();
      setConfigured(data.configured);
    } catch (e) {
      console.error("Failed to check setup status", e);
      setConfigured(false);
    }
  }

  if (configured === null) {
    return <div style={{ width: "100%", height: "100vh", backgroundColor: "#121212" }} />;
  }

  if (!configured) {
    return <SetupPage onSetupComplete={() => setConfigured(true)} />;
  }

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/jobs" element={<JobsPage />} />

        <Route path="/history" element={<HistoryPage />} />

        <Route
          path="/logs"
          element={<LogsPage />}
        />

<Route path="/settings" element={<SettingsPage />} />


        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
