import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/upload", label: "Upload" },
  { to: "/products", label: "Products" },
  { to: "/review", label: "Review Queue" },
];

export default function Navbar() {
  return (
    <header className="navbar">
      <div className="navbar-inner">
        <NavLink to="/upload" className="brand">
          <span className="brand-mark">PC</span>
          <span className="brand-name">
            Product<span>Classifier</span>
          </span>
        </NavLink>

        <nav className="nav-links" aria-label="Main navigation">
          {LINKS.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `nav-link ${isActive ? "nav-link-active" : ""}`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  );
}
