/**
 * Data contracts matching FastAPI backend schemas.
 */

export interface HealthResponse {
  status: string;
  timestamp: string;
  database: string;
  journal_mode: string;
}

export interface SystemInfo {
  app_name: string;
  version: string;
  environment: string;
  host: string;
  port: number;
  database_journal_mode: string;
  worker_status: string;
  api_cost_policy: string;
}

export interface CpuTelemetry {
  usage_percent: number | null;
  physical_cores: number | null;
  logical_cores: number | null;
}

export interface MemoryTelemetry {
  used_gb: number | null;
  total_gb: number | null;
  usage_percent: number | null;
}

export interface GpuTelemetry {
  name: string | null;
  available: boolean;
  vram_used_mb: number | null;
  vram_total_mb: number | null;
}

export interface DiskTelemetry {
  drive: string;
  free_gb: number | null;
  total_gb: number | null;
  usage_percent: number | null;
}

export interface SystemTelemetry {
  cpu: CpuTelemetry;
  memory: MemoryTelemetry;
  gpu: GpuTelemetry;
  disk: DiskTelemetry;
  sampled_at: number;
}

export type NavPage =
  | "dashboard"
  | "agent-office"
  | "workflow-monitor"
  | "content-studio"
  | "human-approval"
  | "analytics"
  | "resource-manager"
  | "settings";
