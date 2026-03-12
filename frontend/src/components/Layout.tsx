import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useState, useRef } from "react";
import { clearToken, getMe, getTokenStats } from "../api";
import type { User, TokenStats } from "../types";
import StatusBar from "./StatusBar";

const NAV = [
  { to: "/", label: "Dashboard", icon: "📊" },
  { to: "/upload", label: "Upload", icon: "🎙️" },
  { to: "/lexicon", label: "Lexicon", icon: "📖" },
  { to: "/blocklist", label: "Blocklist", icon: "🚫" },
  { to: "/anchors", label: "Anchors", icon: "⚓" },
  { to: "/ngram", label: "N-Gram", icon: "🔗" },
  { to: "/self-learning", label: "Self-Learning", icon: "🧠" },
  { to: "/coword-map", label: "Co-Word Map", icon: "🕸️" },
  { to: "/account", label: "Account", icon: "👤" },
];

function formatTokenCount(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(2)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
  return count.toString();
}

export default function Layout() {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const [tokenStats, setTokenStats] = useState<TokenStats | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    getMe()
      .then(setUser)
      .catch(() => {
        clearToken();
        navigate("/login");
      });
    
    // Fetch token stats
    getTokenStats().then(setTokenStats).catch(() => {});
    
    // Poll for token stats every 30 seconds
    pollRef.current = setInterval(() => {
      getTokenStats().then(setTokenStats).catch(() => {});
    }, 30000);
    
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [navigate]);

  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  // Determine progress bar color based on usage
  const getProgressColor = (percentage: number) => {
    if (percentage >= 90) return "bg-red-500";
    if (percentage >= 70) return "bg-amber-500";
    return "bg-sky-500";
  };

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

        <div className="p-3 border-t border-gray-800 space-y-3">
          <StatusBar />
          
          {/* Gemini Usage Stats - All 3 Metrics */}
          {tokenStats && (
            <div className="space-y-2">
              <div className="text-[10px] text-gray-500 flex items-center gap-1 mb-1">
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                <span>Gemini 3.1 Flash Lite</span>
              </div>
              
              {/* RPM - Requests Per Minute */}
              <div className="space-y-0.5">
                <div className="flex items-center justify-between text-[9px] text-gray-500">
                  <span>RPM</span>
                  <span>{tokenStats.requests_per_minute} / {tokenStats.rpm_limit}</span>
                </div>
                <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
                  <div 
                    className={`h-full rounded-full transition-all duration-500 ${getProgressColor((tokenStats.requests_per_minute / tokenStats.rpm_limit) * 100)}`}
                    style={{ width: `${Math.min((tokenStats.requests_per_minute / tokenStats.rpm_limit) * 100, 100)}%` }}
                  />
                </div>
              </div>
              
              {/* TPM - Tokens Per Minute */}
              <div className="space-y-0.5">
                <div className="flex items-center justify-between text-[9px] text-gray-500">
                  <span>TPM</span>
                  <span>{formatTokenCount(tokenStats.tokens_per_minute)} / {formatTokenCount(tokenStats.tpm_limit)}</span>
                </div>
                <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
                  <div 
                    className={`h-full rounded-full transition-all duration-500 ${getProgressColor((tokenStats.tokens_per_minute / tokenStats.tpm_limit) * 100)}`}
                    style={{ width: `${Math.min((tokenStats.tokens_per_minute / tokenStats.tpm_limit) * 100, 100)}%` }}
                  />
                </div>
              </div>
              
              {/* RPD - Requests Per Day */}
              <div className="space-y-0.5">
                <div className="flex items-center justify-between text-[9px] text-gray-500">
                  <span>RPD</span>
                  <span>{tokenStats.requests_today} / {tokenStats.rpd_limit}</span>
                </div>
                <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
                  <div 
                    className={`h-full rounded-full transition-all duration-500 ${getProgressColor((tokenStats.requests_today / tokenStats.rpd_limit) * 100)}`}
                    style={{ width: `${Math.min((tokenStats.requests_today / tokenStats.rpd_limit) * 100, 100)}%` }}
                  />
                </div>
              </div>
              
              {/* All-time totals */}
              <div className="pt-1 border-t border-gray-800/50 space-y-0.5">
                <div className="flex items-center justify-between text-[8px] text-gray-600">
                  <span>Total sessions</span>
                  <span>{tokenStats.sessions_with_gemini}</span>
                </div>
                <div className="flex items-center justify-between text-[8px] text-gray-600">
                  <span>Total tokens</span>
                  <span>{formatTokenCount(tokenStats.total_tokens)}</span>
                </div>
              </div>
            </div>
          )}
          
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
        <div className="max-w-6xl mx-auto px-6 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
