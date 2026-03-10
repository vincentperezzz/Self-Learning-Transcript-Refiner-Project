import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { clearToken, getMe } from "../api";
import type { User } from "../types";
import StatusBar from "./StatusBar";

const NAV = [
  { to: "/", label: "Dashboard", icon: "📊" },
  { to: "/upload", label: "Upload", icon: "🎙️" },
  { to: "/lexicon", label: "Lexicon", icon: "📖" },
  { to: "/blocklist", label: "Blocklist", icon: "🚫" },
  { to: "/anchors", label: "Anchors", icon: "⚓" },
  { to: "/ngram", label: "N-Gram", icon: "🔗" },
  { to: "/self-learning", label: "Self-Learning", icon: "🧠" },
  { to: "/account", label: "Account", icon: "👤" },
];

export default function Layout() {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    getMe()
      .then(setUser)
      .catch(() => {
        clearToken();
        navigate("/login");
      });
  }, [navigate]);

  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col shrink-0 h-screen sticky top-0">
        <div className="p-4 border-b border-gray-800">
          <h1 className="text-lg font-bold tracking-tight">
            Phoenix <span className="text-sky-400">3.0</span>
          </h1>
          <p className="text-[11px] text-gray-500 mt-0.5">Transcript Refiner</p>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? "bg-sky-600/20 text-sky-300"
                    : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
                }`
              }
            >
              <span>{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-gray-800 space-y-2">
          <StatusBar />
          {user && (
            <div className="flex items-center justify-between text-xs text-gray-500">
              <span>
                {user.username}{" "}
                <span className="text-gray-600">({user.role})</span>
              </span>
              <button
                onClick={handleLogout}
                className="text-gray-500 hover:text-red-400 transition-colors"
              >
                Logout
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto h-screen">
        <div className="max-w-5xl mx-auto px-6 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
