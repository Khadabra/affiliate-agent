import type { HealthResponse, SystemInfo, SystemTelemetry } from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request<T>(endpoint: string, timeoutMs = 4000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      signal: controller.signal,
      headers: {
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    return (await response.json()) as T;
  } catch (err: unknown) {
    if (err instanceof Error) {
      if (err.name === "AbortError") {
        throw new Error(`Request timed out after ${timeoutMs}ms`);
      }
      throw err;
    }
    throw new Error("Unknown network error occurred");
  } finally {
    clearTimeout(timer);
  }
}

export const apiClient = {
  baseUrl: API_BASE_URL,

  async getHealth(): Promise<HealthResponse> {
    return request<HealthResponse>("/health");
  },

  async getSystemInfo(): Promise<SystemInfo> {
    return request<SystemInfo>("/api/v1/system/info");
  },

  async getTelemetry(): Promise<SystemTelemetry> {
    return request<SystemTelemetry>("/api/v1/system/resources");
  },
};
