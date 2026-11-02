"""Performance and Conversion Analytics Module.

Implements mathematical conversion analytics, discrepancy checks,
and snapshot aggregation logic that avoids double-counting cumulative counters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from affiliate_factory.models import PerformanceRecord


@dataclass
class ConversionRates:
    """Computed conversion rates from observed performance metrics.

    Never defaults unknown or division-by-zero to 0.0; leaves as None.
    """
    ctr: float | None = None
    click_to_order: float | None = None
    commission_per_order: float | None = None
    commission_per_click: float | None = None


def calculate_conversion_rates(
    views: int | None,
    clicks: int | None,
    orders: int | None,
    commission_idr: float | None = None,
) -> ConversionRates:
    """Compute conversion rates strictly based on available data.

    Rules:
    - CTR = (clicks / views) * 100.0 if views > 0 and clicks is not None.
    - Click-to-order = (orders / clicks) * 100.0 if clicks > 0 and orders is not None.
    - Commission per order = commission_idr / orders if orders > 0 and commission_idr is not None.
    - If denominator is 0 or None, the corresponding rate is None (not 0.0).
    - If numerator is 0 and denominator > 0, the rate is 0.0.
    """
    ctr: float | None = None
    if views is not None and clicks is not None:
        if views > 0:
            ctr = (clicks / views) * 100.0
        # If views == 0, ctr remains None (cannot divide by zero)

    click_to_order: float | None = None
    if clicks is not None and orders is not None:
        if clicks > 0:
            click_to_order = (orders / clicks) * 100.0
        # If clicks == 0, click_to_order remains None

    commission_per_order: float | None = None
    if orders is not None and commission_idr is not None:
        if orders > 0:
            commission_per_order = commission_idr / orders

    commission_per_click: float | None = None
    if clicks is not None and commission_idr is not None:
        if clicks > 0:
            commission_per_click = commission_idr / clicks

    return ConversionRates(
        ctr=ctr,
        click_to_order=click_to_order,
        commission_per_order=commission_per_order,
        commission_per_click=commission_per_click,
    )


def check_metric_anomalies(
    views: int | None,
    clicks: int | None,
    orders: int | None,
) -> list[str]:
    """Inspect metrics for realistic business anomalies and discrepancies.

    Does NOT hard-reject real data, but provides diagnostic warnings
    (e.g. attribution window lag, direct link sharing, or counter update delays).
    """
    warnings: list[str] = []

    if views is not None and clicks is not None and clicks > views:
        warnings.append(
            f"Jumlah klik ({clicks:,}) melebihi jumlah tayangan ({views:,}). "
            f"Kemungkinan penyebab: keterlambatan pembaruan counter tayangan (counter lag) "
            f"atau tautan afiliasi dibagikan langsung di luar platform video."
        )

    if clicks is not None and orders is not None and orders > clicks:
        warnings.append(
            f"Jumlah pesanan ({orders:,}) melebihi jumlah klik ({clicks:,}). "
            f"Kemungkinan penyebab: pembeli melakukan beberapa pesanan terpisah dalam "
            f"jendela atribusi cookie afiliasi yang sama, atau keterlambatan pembaruan klik."
        )

    return warnings


@dataclass
class ContentPerformanceItem:
    """Aggregated performance for a single (content_id, platform) pair."""
    content_id: str
    platform: str
    snapshot_count: int
    first_observed_at: datetime
    latest_observed_at: datetime
    latest_record_id: str | None
    # Latest snapshot metrics (cumulative state as of latest observation)
    views: int | None
    clicks: int | None
    orders: int | None
    commission_idr: float | None
    data_source: str
    # Conversion rates for latest snapshot
    rates: ConversionRates
    # Deltas across window (latest - first) if multiple snapshots exist
    views_delta: int | None = None
    clicks_delta: int | None = None
    orders_delta: int | None = None
    commission_delta: float | None = None


@dataclass
class PerformanceSummary:
    """Summary of performance across multiple content items and snapshots.

    STRATEGY:
    To avoid double-counting cumulative counters from repeated snapshots of the same content,
    this summary selects the LATEST snapshot for each distinct (content_id, platform) pair
    within the queried filter window, and sums those latest snapshots.
    """
    total_content_items: int
    total_snapshots: int
    # Sum of latest metrics across items
    total_views: int | None
    total_clicks: int | None
    total_orders: int | None
    total_commission_idr: float | None
    # Counts of items where metric was unknown (None)
    views_unknown_count: int
    clicks_unknown_count: int
    orders_unknown_count: int
    commission_unknown_count: int
    # Overall factory conversion rates
    aggregate_rates: ConversionRates
    # Per-content breakdown
    items: list[ContentPerformanceItem] = field(default_factory=list)


def calculate_performance_summary(records: list[PerformanceRecord]) -> PerformanceSummary:
    """Aggregate a collection of performance snapshots without double-counting.

    Groups snapshots by (content_id, platform). For each content item, takes the latest
    snapshot as its current cumulative state. Sums latest states across distinct items.
    """
    if not records:
        return PerformanceSummary(
            total_content_items=0,
            total_snapshots=0,
            total_views=None,
            total_clicks=None,
            total_orders=None,
            total_commission_idr=None,
            views_unknown_count=0,
            clicks_unknown_count=0,
            orders_unknown_count=0,
            commission_unknown_count=0,
            aggregate_rates=ConversionRates(),
            items=[],
        )

    # Group by (content_id, platform)
    groups: dict[tuple[str, str], list[PerformanceRecord]] = {}
    for r in records:
        key = (r.content_id, r.platform)
        groups.setdefault(key, []).append(r)

    content_items: list[ContentPerformanceItem] = []

    sum_views = 0
    any_views_known = False
    views_unknown_count = 0

    sum_clicks = 0
    any_clicks_known = False
    clicks_unknown_count = 0

    sum_orders = 0
    any_orders_known = False
    orders_unknown_count = 0

    sum_commission = 0.0
    any_commission_known = False
    commission_unknown_count = 0

    for (c_id, plat), group_recs in groups.items():
        # Sort chronologically
        sorted_recs = sorted(group_recs, key=lambda x: (x.observed_at, x.id or ""))
        first_rec = sorted_recs[0]
        latest_rec = sorted_recs[-1]

        # Calculate deltas if multiple snapshots exist
        v_delta: int | None = None
        c_delta: int | None = None
        o_delta: int | None = None
        comm_delta: float | None = None

        if len(sorted_recs) > 1:
            if latest_rec.views is not None and first_rec.views is not None:
                v_delta = latest_rec.views - first_rec.views
            if latest_rec.clicks is not None and first_rec.clicks is not None:
                c_delta = latest_rec.clicks - first_rec.clicks
            if latest_rec.orders is not None and first_rec.orders is not None:
                o_delta = latest_rec.orders - first_rec.orders
            if latest_rec.commission_idr is not None and first_rec.commission_idr is not None:
                comm_delta = latest_rec.commission_idr - first_rec.commission_idr

        rates = calculate_conversion_rates(
            views=latest_rec.views,
            clicks=latest_rec.clicks,
            orders=latest_rec.orders,
            commission_idr=latest_rec.commission_idr,
        )

        item = ContentPerformanceItem(
            content_id=c_id,
            platform=plat,
            snapshot_count=len(sorted_recs),
            first_observed_at=first_rec.observed_at,
            latest_observed_at=latest_rec.observed_at,
            latest_record_id=latest_rec.id,
            views=latest_rec.views,
            clicks=latest_rec.clicks,
            orders=latest_rec.orders,
            commission_idr=latest_rec.commission_idr,
            data_source=latest_rec.data_source,
            rates=rates,
            views_delta=v_delta,
            clicks_delta=c_delta,
            orders_delta=o_delta,
            commission_delta=comm_delta,
        )
        content_items.append(item)

        # Aggregate metrics from latest snapshot
        if latest_rec.views is not None:
            sum_views += latest_rec.views
            any_views_known = True
        else:
            views_unknown_count += 1

        if latest_rec.clicks is not None:
            sum_clicks += latest_rec.clicks
            any_clicks_known = True
        else:
            clicks_unknown_count += 1

        if latest_rec.orders is not None:
            sum_orders += latest_rec.orders
            any_orders_known = True
        else:
            orders_unknown_count += 1

        if latest_rec.commission_idr is not None:
            sum_commission += latest_rec.commission_idr
            any_commission_known = True
        else:
            commission_unknown_count += 1

    total_views = sum_views if any_views_known else None
    total_clicks = sum_clicks if any_clicks_known else None
    total_orders = sum_orders if any_orders_known else None
    total_commission = sum_commission if any_commission_known else None

    aggregate_rates = calculate_conversion_rates(
        views=total_views,
        clicks=total_clicks,
        orders=total_orders,
        commission_idr=total_commission,
    )

    return PerformanceSummary(
        total_content_items=len(content_items),
        total_snapshots=len(records),
        total_views=total_views,
        total_clicks=total_clicks,
        total_orders=total_orders,
        total_commission_idr=total_commission,
        views_unknown_count=views_unknown_count,
        clicks_unknown_count=clicks_unknown_count,
        orders_unknown_count=orders_unknown_count,
        commission_unknown_count=commission_unknown_count,
        aggregate_rates=aggregate_rates,
        items=content_items,
    )
