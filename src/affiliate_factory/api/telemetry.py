"""Hardware and system resource telemetry service with caching and graceful degradation."""

from __future__ import annotations

import os
import threading
import time
import warnings
from pathlib import Path
from typing import Any

import psutil
from pydantic import BaseModel, Field


class CpuTelemetry(BaseModel):
    usage_percent: float | None = None
    physical_cores: int | None = None
    logical_cores: int | None = None


class MemoryTelemetry(BaseModel):
    used_gb: float | None = None
    total_gb: float | None = None
    usage_percent: float | None = None


class GpuTelemetry(BaseModel):
    name: str | None = None
    available: bool = False
    vram_used_mb: int | None = None
    vram_total_mb: int | None = None


class DiskTelemetry(BaseModel):
    drive: str = "D:"
    free_gb: float | None = None
    total_gb: float | None = None
    usage_percent: float | None = None


class SystemTelemetry(BaseModel):
    cpu: CpuTelemetry = Field(default_factory=CpuTelemetry)
    memory: MemoryTelemetry = Field(default_factory=MemoryTelemetry)
    gpu: GpuTelemetry = Field(default_factory=GpuTelemetry)
    disk: DiskTelemetry = Field(default_factory=DiskTelemetry)
    sampled_at: float = Field(default_factory=time.time)


class TelemetryService:
    """Provides cached telemetry data to avoid CPU/GPU overhead from frequent polling."""

    def __init__(self, target_path: Path | str = ".", cache_ttl_seconds: float = 1.5) -> None:
        self.target_path = Path(target_path).resolve()
        self.cache_ttl_seconds = cache_ttl_seconds
        self._lock = threading.Lock()
        self._cached_telemetry: SystemTelemetry | None = None
        self._last_sample_time: float = 0.0

        # Prime psutil CPU percent initial tick
        psutil.cpu_percent(interval=None)

        # Detect drive
        try:
            self._drive = self.target_path.anchor or "D:\\"
        except Exception:
            self._drive = "D:\\"

        # Check NVML availability once
        self._nvml_available = False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import pynvml

                pynvml.nvmlInit()
                if pynvml.nvmlDeviceGetCount() > 0:
                    self._nvml_available = True
                pynvml.nvmlShutdown()
        except Exception:
            self._nvml_available = False

    def get_telemetry(self, force_refresh: bool = False) -> SystemTelemetry:
        """Return the latest telemetry, using cache if within TTL."""
        now = time.time()
        with self._lock:
            if (
                not force_refresh
                and self._cached_telemetry is not None
                and (now - self._last_sample_time) < self.cache_ttl_seconds
            ):
                return self._cached_telemetry

            telemetry = self._sample(now)
            self._cached_telemetry = telemetry
            self._last_sample_time = now
            return telemetry

    def _sample(self, timestamp: float) -> SystemTelemetry:
        # 1. CPU
        cpu_usage: float | None = None
        try:
            cpu_usage = float(psutil.cpu_percent(interval=None))
        except Exception:
            pass

        cpu = CpuTelemetry(
            usage_percent=cpu_usage,
            physical_cores=psutil.cpu_count(logical=False),
            logical_cores=psutil.cpu_count(logical=True),
        )

        # 2. Memory
        mem = MemoryTelemetry()
        try:
            vm = psutil.virtual_memory()
            mem = MemoryTelemetry(
                used_gb=round(vm.used / (1024**3), 2),
                total_gb=round(vm.total / (1024**3), 2),
                usage_percent=float(vm.percent),
            )
        except Exception:
            pass

        # 3. GPU (NVML with fallback)
        gpu = GpuTelemetry(available=False)
        if self._nvml_available:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    import pynvml

                    pynvml.nvmlInit()
                    device_count = pynvml.nvmlDeviceGetCount()
                    if device_count > 0:
                        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                        gpu_name = pynvml.nvmlDeviceGetName(handle)
                        if isinstance(gpu_name, bytes):
                            gpu_name = gpu_name.decode("utf-8", errors="replace")
                        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        gpu = GpuTelemetry(
                            name=str(gpu_name),
                            available=True,
                            vram_used_mb=int(mem_info.used // (1024 * 1024)),
                            vram_total_mb=int(mem_info.total // (1024 * 1024)),
                        )
                    pynvml.nvmlShutdown()
            except Exception:
                gpu = GpuTelemetry(available=False)

        # 4. Disk
        disk = DiskTelemetry(drive=self._drive)
        try:
            du = psutil.disk_usage(self._drive)
            disk = DiskTelemetry(
                drive=self._drive.rstrip("\\"),
                free_gb=round(du.free / (1024**3), 2),
                total_gb=round(du.total / (1024**3), 2),
                usage_percent=float(du.percent),
            )
        except Exception:
            pass

        return SystemTelemetry(
            cpu=cpu,
            memory=mem,
            gpu=gpu,
            disk=disk,
            sampled_at=timestamp,
        )
