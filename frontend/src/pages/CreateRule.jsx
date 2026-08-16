import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../services/api";

export default function CreateRule() {
  const [keyword, setKeyword] = useState("");
  const [dmMessage, setDmMessage] = useState("");
  const [status, setStatus] = useState(null);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setStatus("saving");
    try {
      await api.createRule(keyword, dmMessage);
      setStatus("done");
      navigate("/rules");
    } catch (err) {
      setStatus("error: " + err.message);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="form">
      <label>
        Keyword
        <input value={keyword} onChange={(e) => setKeyword(e.target.value)} required />
      </label>
      <label>
        DM Message
        <textarea value={dmMessage} onChange={(e) => setDmMessage(e.target.value)} required />
      </label>
      <button type="submit">Create Rule</button>
      {status === "saving" && <p>Saving...</p>}
      {status && status.startsWith("error") && <p className="error">{status}</p>}
    </form>
  );
}
