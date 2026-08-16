import { useEffect, useState } from "react";
import { api } from "../services/api";

export default function RulesList() {
  const [rules, setRules] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listRules().then((r) => setRules(r.rules)).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!rules) return <p>Loading...</p>;
  if (rules.length === 0) return <p>No rules yet.</p>;

  return (
    <table className="table">
      <thead>
        <tr><th>Keyword</th><th>DM Message</th></tr>
      </thead>
      <tbody>
        {rules.map((r) => (
          <tr key={r.rule_id}>
            <td>{r.keyword}</td>
            <td>{r.dm_message}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
