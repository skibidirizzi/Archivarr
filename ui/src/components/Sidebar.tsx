import { NavLink } from "react-router-dom";
import smLogo from "../assets/smlogo.png";

const navItems = [
  { to: "/", label: "Dashboard" },
  { to: "/jobs", label: "Archive Jobs" },
  { to: "/history", label: "History" },
  { to: "/logs", label: "Logs" },
  { to: "/settings", label: "Settings" },
];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <img 
          src={smLogo}
          alt="Archivarr" 
          style={{ width: "36px", height: "36px", borderRadius: "8px" }}
        />
      </div>

      <nav className="nav">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => "navItem" + (isActive ? " active" : "")}
            end={item.to === "/"}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="sidebarFooter">
        <div className="muted">Standalone *arr-style archiver</div>
      </div>
    </aside>
  );
}
