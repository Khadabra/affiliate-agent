import React from "react";
import type { NavPage } from "../../types";

interface SidebarProps {
  currentPage: NavPage;
  onNavigate: (page: NavPage) => void;
}

interface NavItem {
  id: NavPage;
  label: string;
  icon: string;
  badge?: string;
  phase?: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: "dashboard", label: "Dashboard", icon: "📊" },
  { id: "agent-office", label: "Agent Office", icon: "🏢", phase: "3.5.3" },
  { id: "workflow-monitor", label: "Workflow Monitor", icon: "⚡", phase: "3.5.3" },
  { id: "content-studio", label: "Content Studio", icon: "✍", phase: "3.5.4" },
  { id: "human-approval", label: "Human Approval", icon: "🛡", phase: "3.5.4", badge: "Gate" },
  { id: "analytics", label: "Analytics & Ranker", icon: "📈", phase: "3.5.5" },
  { id: "resource-manager", label: "Resource Manager", icon: "🎛", phase: "3.5.2" },
  { id: "settings", label: "Settings", icon: "⚙" },
];

export const Sidebar: React.FC<SidebarProps> = ({ currentPage, onNavigate }) => {
  return (
    <aside className="sidebar">
      {/* Brand header */}
      <div
        style={{
          padding: "20px 24px",
          borderBottom: "1px solid var(--border-color)",
          display: "flex",
          alignItems: "center",
          gap: "10px",
        }}
      >
        <span style={{ fontSize: "1.5rem" }}>🚀</span>
        <div>
          <div style={{ fontWeight: 700, fontSize: "0.95rem", color: "var(--text-primary)" }}>
            Affiliate Factory
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            Phase 3.5.1 Foundation
          </div>
        </div>
      </div>

      {/* Navigation menu */}
      <nav style={{ padding: "16px 12px", display: "flex", flexDirection: "column", gap: "4px", flex: 1 }}>
        {NAV_ITEMS.map((item) => {
          const isActive = currentPage === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px",
                borderRadius: "6px",
                border: "none",
                background: isActive ? "var(--accent-bg)" : "transparent",
                color: isActive ? "var(--accent-primary)" : "var(--text-secondary)",
                fontWeight: isActive ? 600 : 500,
                fontSize: "0.875rem",
                cursor: "pointer",
                textAlign: "left",
                transition: "all 0.15s ease",
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = "var(--bg-card-hover)";
                  e.currentTarget.style.color = "var(--text-primary)";
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = "transparent";
                  e.currentTarget.style.color = "var(--text-secondary)";
                }
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span>{item.icon}</span>
                <span>{item.label}</span>
              </div>
              {item.badge && (
                <span
                  style={{
                    fontSize: "0.65rem",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    backgroundColor: "var(--warning-bg)",
                    color: "var(--warning-text)",
                    fontWeight: 700,
                  }}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Footer Info */}
      <div
        style={{
          padding: "16px 20px",
          borderTop: "1px solid var(--border-color)",
          fontSize: "0.75rem",
          color: "var(--text-muted)",
          display: "flex",
          flexDirection: "column",
          gap: "4px",
        }}
      >
        <div>Runtime: <strong>Python 3.12 + FastAPI</strong></div>
        <div>Mode: <strong>Local-Only (127.0.0.1)</strong></div>
        <div>Cost: <strong>Rp 0 Mandatory API</strong></div>
      </div>
    </aside>
  );
};
