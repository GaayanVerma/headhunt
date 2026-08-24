import { NavLink, Route, Routes } from "react-router-dom";
import { ClassicSearch } from "./pages/ClassicSearch";
import { ChatAssistant } from "./pages/ChatAssistant";
import { SessionStatusBadge } from "./components/SessionStatusBadge";

export function App() {
  return (
    <div className="app-shell">
      <aside className="rail">
        <div className="rail-brand">
          Sourcing Console
          <small>x-ray + linkedin</small>
        </div>
        <nav className="rail-nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            Classic search
          </NavLink>
          <NavLink to="/chat" className={({ isActive }) => (isActive ? "active" : "")}>
            AI assistant
          </NavLink>
        </nav>
        <div style={{ marginTop: "auto" }}>
          <SessionStatusBadge />
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<ClassicSearch />} />
          <Route path="/chat" element={<ChatAssistant />} />
        </Routes>
      </main>
    </div>
  );
}
