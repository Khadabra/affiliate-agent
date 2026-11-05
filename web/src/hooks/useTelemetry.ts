import { useEffect, useState, useCallback } from "react";
import { apiClient } from "../api/client";
import type { HealthResponse, SystemInfo, SystemTelemetry } from "../types";

export interface TelemetryState {
  health: HealthResponse | null;
  systemInfo: SystemInfo | null;
  telemetry: SystemTelemetry | null;
  isOnline: boolean;
  isLoading: boolean;
  lastUpdated: Date | null;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useTelemetry(intervalMs = 3000): TelemetryState {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [telemetry, setTelemetry] = useState<SystemTelemetry | null>(null);
  const [isOnline, setIsOnline] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      // 1. Fetch Health
      const healthData = await apiClient.getHealth();
      setHealth(healthData);
      setIsOnline(true);
      setError(null);

      // 2. Fetch System Info (if not already fetched)
      if (!systemInfo) {
        try {
          const info = await apiClient.getSystemInfo();
          setSystemInfo(info);
        } catch {
          // non-critical if info endpoint fails
        }
      }

      // 3. Fetch Telemetry
      const telemData = await apiClient.getTelemetry();
      setTelemetry(telemData);
      setLastUpdated(new Date());
    } catch (err: unknown) {
      setIsOnline(false);
      const msg = err instanceof Error ? err.message : "Failed to connect to API";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [systemInfo]);

  useEffect(() => {
    // Initial fetch
    fetchAll();

    // Periodic polling
    const timer = setInterval(() => {
      // Only poll if window is visible to conserve client CPU
      if (document.visibilityState === "visible") {
        fetchAll();
      }
    }, intervalMs);

    return () => clearInterval(timer);
  }, [fetchAll, intervalMs]);

  return {
    health,
    systemInfo,
    telemetry,
    isOnline,
    isLoading,
    lastUpdated,
    error,
    refetch: fetchAll,
  };
}
