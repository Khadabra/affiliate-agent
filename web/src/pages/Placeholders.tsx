import React from "react";
import type { NavPage } from "../types";

interface PlaceholderProps {
  page: NavPage;
  theme: "dark" | "light";
  onSetTheme: (theme: "dark" | "light") => void;
  onNavigateHome: () => void;
}

export const PlaceholderPage: React.FC<PlaceholderProps> = ({
  page,
  theme,
  onSetTheme,
  onNavigateHome,
}) => {
  if (page === "settings") {
    return (
      <div className="page-body">
        <div style={{ marginBottom: "24px" }}>
          <h1 style={{ fontSize: "1.75rem", fontWeight: 700, marginBottom: "6px" }}>Settings</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.95rem" }}>
            Application appearance, operational policies, and environment configuration.
          </p>
        </div>

        <div className="card" style={{ maxWidth: "680px", marginBottom: "20px" }}>
          <h3 style={{ fontSize: "1.05rem", fontWeight: 600, marginBottom: "16px" }}>
            Appearance & Theme
          </h3>
          <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginBottom: "16px" }}>
            Select your preferred interface appearance. Theme preference is automatically saved locally.
          </p>

          <div style={{ display: "flex", gap: "16px" }}>
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "10px 16px",
                border: "1px solid var(--border-color)",
                borderRadius: "6px",
                backgroundColor: theme === "dark" ? "var(--accent-bg)" : "var(--bg-secondary)",
                color: theme === "dark" ? "var(--accent-primary)" : "var(--text-primary)",
                cursor: "pointer",
                fontWeight: theme === "dark" ? 600 : 400,
              }}
            >
              <input
                type="radio"
                name="theme"
                value="dark"
                checked={theme === "dark"}
                onChange={() => onSetTheme("dark")}
              />
              🌙 Dark Mode (Default)
            </label>

            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "10px 16px",
                border: "1px solid var(--border-color)",
                borderRadius: "6px",
                backgroundColor: theme === "light" ? "var(--accent-bg)" : "var(--bg-secondary)",
                color: theme === "light" ? "var(--accent-primary)" : "var(--text-primary)",
                cursor: "pointer",
                fontWeight: theme === "light" ? 600 : 400,
              }}
            >
              <input
                type="radio"
                name="theme"
                value="light"
                checked={theme === "light"}
                onChange={() => onSetTheme("light")}
              />
              ☀ Light Mode
            </label>
          </div>
        </div>

        <div className="card" style={{ maxWidth: "680px", marginBottom: "20px" }}>
          <h3 style={{ fontSize: "1.05rem", fontWeight: 600, marginBottom: "16px" }}>
            Operational Invariants (Fixed Rules)
          </h3>
          <ul style={{ fontSize: "0.85rem", color: "var(--text-secondary)", display: "flex", flexDirection: "column", gap: "10px", paddingLeft: "20px" }}>
            <li><strong>Zero Mandatory API Cost:</strong> No paid AI keys required to run. Offline manual input available.</li>
            <li><strong>Human Approval Mandatory:</strong> Content cannot be exported or published without explicit review approval.</li>
            <li><strong>Strict Localhost Binding:</strong> FastAPI server binds strictly to <code>127.0.0.1</code>.</li>
            <li><strong>Resource Guard:</strong> Maximum 1 heavy job at a time. Local LLM and FFmpeg rendering never run concurrently.</li>
          </ul>
        </div>

        <button className="btn btn-secondary" onClick={onNavigateHome}>
          ← Back to Dashboard Overview
        </button>
      </div>
    );
  }

  const metaMap: Record<NavPage, { title: string; phase: string; desc: string; icon: string }> = {
    "agent-office": {
      title: "Agent Office",
      phase: "Phase 3.5.3",
      desc: "Observability center for the 7 deterministic specialist agents (Research, ContentWriter, FactChecker, Compliance, ApprovalGate, Export, Analytics).",
      icon: "🏢",
    },
    "workflow-monitor": {
      title: "Workflow Monitor",
      phase: "Phase 3.5.3",
      desc: "Real-time DAG execution visualizer with Server-Sent Events (SSE) stream, step progression, and safe task recovery controls.",
      icon: "⚡",
    },
    "content-studio": {
      title: "Content Studio",
      phase: "Phase 3.5.4",
      desc: "Product intake wizard, structured copywriting prompt builder, and script generator with multiple angle selections.",
      icon: "✍",
    },
    "human-approval": {
      title: "Human Approval Center",
      phase: "Phase 3.5.4",
      desc: "Strict review gate UI: verify claims, inspect compliance rules fail-closed status, and issue explicit APPROVE or REJECT decisions.",
      icon: "🛡",
    },
    "analytics": {
      title: "Analytics & Angle Ranker",
      phase: "Phase 3.5.5",
      desc: "Empirical conversion performance tracking, CTR/CVR/AOV/RPC analytics, and CopywritingAdvisor recommendations.",
      icon: "📈",
    },
    "resource-manager": {
      title: "Resource Manager",
      phase: "Phase 3.5.2",
      desc: "Live workstation telemetry guard, persistent job queue leasing, manual worker startup controls, and NVENC/VRAM mutex locks.",
      icon: "🎛",
    },
    dashboard: { title: "Dashboard", phase: "Current", desc: "", icon: "📊" },
    settings: { title: "Settings", phase: "Current", desc: "", icon: "⚙" },
  };

  const current = metaMap[page];

  return (
    <div className="page-body">
      <div style={{ marginBottom: "24px" }}>
        <h1 style={{ fontSize: "1.75rem", fontWeight: 700, marginBottom: "6px" }}>
          {current.icon} {current.title}
        </h1>
        <p style={{ color: "var(--text-secondary)", fontSize: "0.95rem" }}>{current.desc}</p>
      </div>

      <div
        className="card"
        style={{
          maxWidth: "600px",
          textAlign: "center",
          padding: "48px 32px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "16px",
        }}
      >
        <div style={{ fontSize: "3rem" }}>{current.icon}</div>
        <div className="badge badge-accent">{current.phase} Scheduled Implementation</div>
        <h3 style={{ fontSize: "1.2rem", fontWeight: 600 }}>Module Under Construction</h3>
        <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", maxWidth: "440px", lineHeight: "1.5" }}>
          This module is part of the incremental roadmap. Phase 3.5.1 establishes the solid FastAPI backend,
          SQLite WAL hardening, and React layout shell before connecting this view.
        </p>
        <button className="btn btn-primary" onClick={onNavigateHome} style={{ marginTop: "12px" }}>
          Return to Dashboard Overview
        </button>
      </div>
    </div>
  );
};
