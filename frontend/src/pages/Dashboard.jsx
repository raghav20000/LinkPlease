import { useEffect, useState } from "react";
import { api } from "../services/api";

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  async function load() {
    try {
      setStats(await api.getStats());
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  if (error) return <p className="error">Could not reach backend: {error}</p>;
  if (!stats) return <p>Loading...</p>;

  return (
    <div className="stats-grid">
      <StatCard label="Sent" value={stats.sent} />
      <StatCard label="Failed" value={stats.failed} />
      <StatCard label="Queued" value={stats.queued} />
      <StatCard label="Duplicates Blocked" value={stats.duplicates_blocked} />
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className="card">
      <div className="card-value">{value}</div>
      <div className="card-label">{label}</div>
    </div>
  );
}
