import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import CreateRule from "./pages/CreateRule.jsx";
import RulesList from "./pages/RulesList.jsx";
import "./styles.css";

function App() {
  return (
    <BrowserRouter>
      <nav className="nav">
        <span className="brand">LinkPlease</span>
        <NavLink to="/" end>Dashboard</NavLink>
        <NavLink to="/rules">Rules</NavLink>
        <NavLink to="/rules/new">Create Rule</NavLink>
      </nav>
      <main className="container">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/rules" element={<RulesList />} />
          <Route path="/rules/new" element={<CreateRule />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
