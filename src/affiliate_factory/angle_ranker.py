"""AngleRanker Module.

Deterministically aggregates performance metrics across mapped content angles,
enforces cumulative snapshot deduplication per independent content item,
isolates cross-platform comparisons by default, and reports proof confidence.
"""

from __future__ import annotations

from typing import Sequence
from affiliate_factory.db import Database
from affiliate_factory.models import (
    AnglePerformanceMetrics,
    AngleRankItem,
    AngleRankReport,
    ContentDraft,
    PerformanceRecord,
    UnmappedContentItem,
)


class AngleRanker:
    """Ranks copywriting angles based on empirical conversion and engagement metrics."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db

    def rank_angles(
        self,
        records: list[PerformanceRecord] | None = None,
        drafts: list[ContentDraft] | None = None,
        platform: str | None = None,
        product_id: str | None = None,
        min_samples: int = 3,
        sort_by: str = "click_to_order",
        allow_cross_platform: bool = False,
    ) -> AngleRankReport:
        """Aggregate performance snapshots and rank content angles.

        Invariants:
        1. Snapshot deduplication: multiple snapshots of the same (content_id, platform)
           are NOT counted as multiple independent contents. The latest snapshot in window
           is used as the cumulative content state.
        2. Draft identity integrity: performance records are mapped to drafts only if
           an unambiguous 1-to-1 draft exists. Drafts not found or having multiple prompt
           versions are categorized as unmapped and excluded from angle metrics.
        3. Platform isolation: by default (allow_cross_platform=False), cross-platform mixing
           is forbidden. If platform is not specified, all records must belong to a single
           platform, or a ValueError is raised requiring explicit platform or flag.
        4. No fake ranks: angles with 0 performance records receive rank=None.
        5. Cohort-based weighted metrics: CTR and Click-to-Order are calculated strictly
           over valid cohorts where both numerator and denominator are known.
        """
        # 1. Fetch data from DB if not provided
        if records is None:
            if self.db is not None:
                records = self.db.list_performance_records(
                    platform=platform.strip() if platform and not allow_cross_platform else None
                )
            else:
                records = []

        if drafts is None:
            if self.db is not None:
                drafts = self.db.list_all_drafts()
            else:
                drafts = []

        # 2. Filter records by platform if specified
        target_platform: str | None = None
        if platform and platform.strip():
            clean_plat = platform.strip()
            records = [r for r in records if r.platform.lower() == clean_plat.lower()]
            target_platform = clean_plat
        elif not allow_cross_platform:
            # Check distinct platforms in records
            distinct_platforms = {r.platform for r in records}
            if len(distinct_platforms) > 1:
                raise ValueError(
                    f"Data lintas platform terdeteksi ({', '.join(sorted(distinct_platforms))}). "
                    f"Tentukan parameter platform secara spesifik atau gunakan allow_cross_platform=True "
                    f"secara eksplisit untuk mencegah percampuran data audiens antarplatform."
                )
            elif len(distinct_platforms) == 1:
                target_platform = next(iter(distinct_platforms))

        # 3. Deduplicate cumulative snapshots per (content_id, platform)
        # Groups snapshots chronologically and takes latest snapshot
        groups: dict[tuple[str, str], list[PerformanceRecord]] = {}
        for r in records:
            key = (r.content_id.strip(), r.platform.strip())
            groups.setdefault(key, []).append(r)

        independent_contents: list[tuple[str, str, PerformanceRecord, int]] = []
        for (c_id, plat), snap_list in groups.items():
            # Deterministic chronological sort: (observed_at ASC, id ASC)
            sorted_snaps = sorted(snap_list, key=lambda x: (x.observed_at, x.id or ""))
            latest_snap = sorted_snaps[-1]
            snapshot_count = len(sorted_snaps)
            independent_contents.append((c_id, plat, latest_snap, snapshot_count))

        # 4. Build draft lookup dictionary by draft_id
        drafts_by_id: dict[str, list[ContentDraft]] = {}
        for d in drafts:
            drafts_by_id.setdefault(d.id.strip(), []).append(d)

        # 5. Resolve content items to drafts and angles
        mapped_by_angle: dict[str, list[tuple[PerformanceRecord, int]]] = {}
        unmapped_items: list[UnmappedContentItem] = []

        for c_id, plat, latest_snap, snap_cnt in independent_contents:
            matching_drafts = drafts_by_id.get(c_id, [])

            if not matching_drafts:
                unmapped_items.append(
                    UnmappedContentItem(
                        content_id=c_id,
                        platform=plat,
                        latest_snapshot_id=latest_snap.id,
                        reason="Draft tidak ditemukan di tabel content_drafts",
                    )
                )
                continue

            if len(matching_drafts) > 1:
                pvs = [d.prompt_version for d in matching_drafts]
                unmapped_items.append(
                    UnmappedContentItem(
                        content_id=c_id,
                        platform=plat,
                        latest_snapshot_id=latest_snap.id,
                        reason=f"Versi prompt ambigu ({len(matching_drafts)} versi ditemukan: {pvs})",
                    )
                )
                continue

            # Exactly 1 draft found
            draft = matching_drafts[0]

            # Filter product_id if requested
            if product_id and product_id.strip():
                if draft.product_id != product_id.strip():
                    continue

            angle = draft.angle.strip()
            mapped_by_angle.setdefault(angle, []).append((latest_snap, snap_cnt))

        # 6. Collect all known angles in repository (to include angles with 0 performance)
        all_known_angles: set[str] = set()
        for d in drafts:
            if product_id and product_id.strip():
                if d.product_id != product_id.strip():
                    continue
            all_known_angles.add(d.angle.strip())

        for angle in all_known_angles:
            if angle not in mapped_by_angle:
                mapped_by_angle[angle] = []

        # 7. Aggregate metrics for each angle
        ranked_candidates: list[AnglePerformanceMetrics] = []
        unranked_angles: list[AngleRankItem] = []

        for angle, items in mapped_by_angle.items():
            if not items:
                # Angle with NO performance records
                unranked_angles.append(
                    AngleRankItem(
                        rank=None,
                        metrics=AnglePerformanceMetrics(
                            angle=angle,
                            total_contents=0,
                            total_snapshots=0,
                            total_views=None,
                            total_clicks=None,
                            total_orders=None,
                            total_commission_idr=None,
                            confidence_label="TIDAK ADA DATA",
                            data_quality_note="Belum ada konten independen dengan data performa yang tercatat untuk angle ini.",
                        ),
                    )
                )
                continue

            total_contents = len(items)
            total_snapshots = sum(snap_cnt for _, snap_cnt in items)

            # Sum of latest states
            sum_views = sum(rec.views for rec, _ in items if rec.views is not None)
            views_known = sum(1 for rec, _ in items if rec.views is not None)
            views_unknown = total_contents - views_known
            total_views = sum_views if views_known > 0 else None

            sum_clicks = sum(rec.clicks for rec, _ in items if rec.clicks is not None)
            clicks_known = sum(1 for rec, _ in items if rec.clicks is not None)
            clicks_unknown = total_contents - clicks_known
            total_clicks = sum_clicks if clicks_known > 0 else None

            sum_orders = sum(rec.orders for rec, _ in items if rec.orders is not None)
            orders_known = sum(1 for rec, _ in items if rec.orders is not None)
            orders_unknown = total_contents - orders_known
            total_orders = sum_orders if orders_known > 0 else None

            sum_comm = sum(rec.commission_idr for rec, _ in items if rec.commission_idr is not None)
            comm_known = sum(1 for rec, _ in items if rec.commission_idr is not None)
            comm_unknown = total_contents - comm_known
            total_comm = sum_comm if comm_known > 0 else None

            # Check if completely devoid of any known metric
            if views_known == 0 and clicks_known == 0 and orders_known == 0 and comm_known == 0:
                unranked_angles.append(
                    AngleRankItem(
                        rank=None,
                        metrics=AnglePerformanceMetrics(
                            angle=angle,
                            total_contents=total_contents,
                            total_snapshots=total_snapshots,
                            total_views=None,
                            total_clicks=None,
                            total_orders=None,
                            total_commission_idr=None,
                            views_known_count=0,
                            views_unknown_count=views_unknown,
                            clicks_known_count=0,
                            clicks_unknown_count=clicks_unknown,
                            orders_known_count=0,
                            orders_unknown_count=orders_unknown,
                            commission_known_count=0,
                            commission_unknown_count=comm_unknown,
                            confidence_label="TIDAK ADA DATA",
                            data_quality_note="Seluruh observasi metrik bernilai tidak diketahui (None).",
                        ),
                    )
                )
                continue

            # Strict Weighted CTR Cohort (both views and clicks known)
            ctr_pairs = [
                (rec.views, rec.clicks)
                for rec, _ in items
                if rec.views is not None and rec.clicks is not None
            ]
            ctr_views_cohort = sum(v for v, c in ctr_pairs)
            ctr_clicks_cohort = sum(c for v, c in ctr_pairs)
            ctr_cohort_count = len(ctr_pairs)
            ctr: float | None = None
            if ctr_cohort_count > 0 and ctr_views_cohort > 0:
                ctr = (ctr_clicks_cohort / ctr_views_cohort) * 100.0

            # Strict Weighted Click-to-Order Cohort (both clicks and orders known)
            cr_pairs = [
                (rec.clicks, rec.orders)
                for rec, _ in items
                if rec.clicks is not None and rec.orders is not None
            ]
            cr_clicks_cohort = sum(c for c, o in cr_pairs)
            cr_orders_cohort = sum(o for c, o in cr_pairs)
            cr_cohort_count = len(cr_pairs)
            click_to_order: float | None = None
            if cr_cohort_count > 0 and cr_clicks_cohort > 0:
                click_to_order = (cr_orders_cohort / cr_clicks_cohort) * 100.0

            # Confidence label
            if total_contents >= min_samples:
                conf_label = "BUKTI CUKUP"
                note = f"Memenuhi batas sampel minimum ({total_contents} >= {min_samples} konten independen)."
            else:
                conf_label = "BUKTI TERBATAS"
                note = f"Sampel hanya {total_contents} konten (< batas minimum {min_samples}). Hasil belum dapat disimpulkan secara reliabel."

            m = AnglePerformanceMetrics(
                angle=angle,
                total_contents=total_contents,
                total_snapshots=total_snapshots,
                total_views=total_views,
                total_clicks=total_clicks,
                total_orders=total_orders,
                total_commission_idr=total_comm,
                views_known_count=views_known,
                views_unknown_count=views_unknown,
                clicks_known_count=clicks_known,
                clicks_unknown_count=clicks_unknown,
                orders_known_count=orders_known,
                orders_unknown_count=orders_unknown,
                commission_known_count=comm_known,
                commission_unknown_count=comm_unknown,
                ctr_cohort_count=ctr_cohort_count,
                ctr_views_cohort=ctr_views_cohort,
                ctr_clicks_cohort=ctr_clicks_cohort,
                ctr=ctr,
                cr_cohort_count=cr_cohort_count,
                cr_clicks_cohort=cr_clicks_cohort,
                cr_orders_cohort=cr_orders_cohort,
                click_to_order=click_to_order,
                confidence_label=conf_label,
                data_quality_note=note,
            )
            ranked_candidates.append(m)

        # 8. Sort ranked candidates deterministically
        def get_sort_key(m: AnglePerformanceMetrics):
            if sort_by == "click_to_order":
                p1 = m.click_to_order if m.click_to_order is not None else float("-inf")
                p2 = m.ctr if m.ctr is not None else float("-inf")
            elif sort_by == "ctr":
                p1 = m.ctr if m.ctr is not None else float("-inf")
                p2 = m.click_to_order if m.click_to_order is not None else float("-inf")
            elif sort_by == "commission":
                p1 = m.total_commission_idr if m.total_commission_idr is not None else float("-inf")
                p2 = m.click_to_order if m.click_to_order is not None else float("-inf")
            elif sort_by == "orders":
                p1 = float(m.total_orders) if m.total_orders is not None else float("-inf")
                p2 = float(m.total_clicks) if m.total_clicks is not None else float("-inf")
            elif sort_by == "views":
                p1 = float(m.total_views) if m.total_views is not None else float("-inf")
                p2 = float(m.total_clicks) if m.total_clicks is not None else float("-inf")
            else:
                p1 = m.click_to_order if m.click_to_order is not None else float("-inf")
                p2 = m.ctr if m.ctr is not None else float("-inf")

            # Deterministic tie-breaker:
            # 1. Primary metric (DESC)
            # 2. Secondary metric (DESC)
            # 3. Total contents (DESC)
            # 4. Inverted ASCII for angle name (ASC when sorting descending)
            angle_neg = [-ord(c) for c in m.angle]
            return (p1, p2, m.total_contents, angle_neg)

        ranked_candidates.sort(key=get_sort_key, reverse=True)

        ranked_angles: list[AngleRankItem] = [
            AngleRankItem(rank=idx, metrics=m)
            for idx, m in enumerate(ranked_candidates, start=1)
        ]

        # Sort unranked angles alphabetically
        unranked_angles.sort(key=lambda x: x.metrics.angle)

        mapped_count = sum(len(items) for items in mapped_by_angle.values() if items)

        return AngleRankReport(
            platform=target_platform,
            product_id=product_id.strip() if product_id else None,
            min_samples=min_samples,
            sort_by=sort_by,
            total_independent_contents=len(independent_contents),
            mapped_contents_count=mapped_count,
            unmapped_contents_count=len(unmapped_items),
            ranked_angles=ranked_angles,
            unranked_angles=unranked_angles,
            unmapped_items=unmapped_items,
            is_cross_platform=allow_cross_platform,
        )
