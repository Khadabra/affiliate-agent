import React, { useEffect, useState } from "react";
import { Header } from "./components/layout/Header";
import { Sidebar } from "./components/layout/Sidebar";
import { useTelemetry } from "./hooks/useTelemetry";
import { DashboardOverview } from "./pages/DashboardOverview";
import { PlaceholderPage } from "./pages/Placeholders";
import type { NavPage } from "./types";
import "./styles/theme.css";

const THEME_STORAGE_KEY = "affiliate_factory_theme";

export const App: React.FC = () => {
  // Theme state: defaults to dark
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return saved === "light" ? "light" : "dark";
  });

  // Navigation state
  const [currentPage, setCurrentPage] = useState<NavPage>("dashboard");

  // Real-time telemetry & health hook
  const { health, systemInfo, telemetry, isOnline, isLoading, error, refetch } = useTelemetry(3000);

  // Sync theme to DOM
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  };

  return (
    <div className="app-container">
      <Sidebar currentPage={currentPage} onNavigate={setCurrentPage} />

      <div className="main-content">
        <Header
          theme={theme}
          onToggleTheme={toggleTheme}
          isOnline={isOnline}
          telemetry={telemetry}
          onRefresh={refetch}
          isLoading={isLoading}
        />

        {currentPage === "dashboard" ? (
          <DashboardOverview
            health={health}
            systemInfo={systemInfo}
            telemetry={telemetry}
            isOnline={isOnline}
            isLoading={isLoading}
            error={error}
            onNavigate={setCurrentPage}
            onRefresh={refetch}
          />
        ) : (
          <PlaceholderPage
            page={currentPage}
            theme={theme}
            onSetTheme={setTheme}
            onNavigateHome={() => setCurrentPage("dashboard")}
          />
        )}
      </div>
    </div>
  );
};

export default App;
