"""Unit and regression tests for Phase 2 Performance Tracking & Conversion Analytics.

Covers:
- Storing and reading snapshots in SQLite.
- Retaining full snapshot history without overwriting previous snapshots.
- Preservation of None (unknown metrics) without converting to zero.
- Rejection of negative metric values (views, clicks, orders, commission).
- Validation and rejection of invalid ISO timestamps.
- Conversion rate calculation invariants (division by zero, None vs 0.0).
- Anomaly warnings when clicks > views or orders > clicks (without hard-rejecting real data).
- Aggregation methodology: summing latest snapshots per content item, never double-counting cumulative counters.
- Filtering by content_id, platform, and date ranges.
- Explicit snapshot ID conflict handling.
- CLI smoke tests for record, show, and summary subcommands with expected exit codes and outputs.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from affiliate_factory.analytics import (
    calculate_conversion_rates,
    calculate_performance_summary,
    check_metric_anomalies,
)
from affiliate_factory.cli import main
from affiliate_factory.db import Database
from affiliate_factory.models import ContentDraft, PerformanceRecord, Product


class TestPerformanceTracking(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_perf.db"
        self.db = Database(self.db_path)

        # Insert a sample product and approved draft for reference
        self.product = Product(
            id="prod_perf_01",
            name="Ring Light 26cm Tripod",
            url="https://shopee.co.id/ring-light-26cm",
            price=85000.0,
            price_observed_at=datetime.now(timezone.utc),
            source="manual",
        )
        self.db.insert_product(self.product)

        self.draft = ContentDraft(
            id="draft_perf_01",
            product_id=self.product.id,
            angle="Lighting Setup",
            hook="Video buram dan gelap bikin penonton kabur?",
            script="Ring light 26cm ini punya 3 mode cahaya dan 10 level terang.",
            caption="Upgrade pencahayaan live dan video kamu sekarang! #ShopeeAffiliate #KontenAI",
            cta="Beli di keranjang kuning profil sekarang!",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="approved",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(self.draft)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # 1. Single snapshot storage and retrieval
    def test_record_and_retrieve_single_snapshot(self) -> None:
        now_utc = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        record = PerformanceRecord(
            content_id="draft_perf_01",
            platform="Shopee Video",
            observed_at=now_utc,
            views=1500,
            clicks=45,
            orders=3,
            commission_idr=15000.0,
            data_source="manual",
        )
        rec_id = self.db.save_performance_record("perf_snap_01", record)
        self.assertEqual(rec_id, "perf_snap_01")

        retrieved = self.db.get_performance_record("perf_snap_01")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, "perf_snap_01")
        self.assertEqual(retrieved.content_id, "draft_perf_01")
        self.assertEqual(retrieved.platform, "Shopee Video")
        self.assertEqual(retrieved.observed_at, now_utc)
        self.assertEqual(retrieved.views, 1500)
        self.assertEqual(retrieved.clicks, 45)
        self.assertEqual(retrieved.orders, 3)
        self.assertEqual(retrieved.commission_idr, 15000.0)
        self.assertEqual(retrieved.data_source, "manual")

    # 2. Retain full snapshot history without overwriting previous snapshots
    def test_multiple_snapshots_retained_chronologically_no_overwrite(self) -> None:
        t1 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)

        r1 = PerformanceRecord(
            content_id="draft_perf_01",
            platform="Shopee Video",
            observed_at=t1,
            views=500,
            clicks=15,
            orders=1,
            commission_idr=5000.0,
        )
        r2 = PerformanceRecord(
            content_id="draft_perf_01",
            platform="Shopee Video",
            observed_at=t2,
            views=1200,
            clicks=40,
            orders=3,
            commission_idr=15000.0,
        )

        self.db.save_performance_record("snap_day_1", r1)
        self.db.save_performance_record("snap_day_2", r2)

        # Both snapshots must be preserved
        history = self.db.list_performance_records(content_id="draft_perf_01")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].id, "snap_day_1")
        self.assertEqual(history[0].views, 500)
        self.assertEqual(history[1].id, "snap_day_2")
        self.assertEqual(history[1].views, 1200)

    # 3. Unknown fields remain None, never defaulted to 0
    def test_unknown_fields_remain_none_never_defaulted_to_zero(self) -> None:
        record = PerformanceRecord(
            content_id="draft_perf_01",
            platform="TikTok",
            views=800,
            # clicks, orders, commission are omitted (unknown)
        )
        self.assertIsNone(record.clicks)
        self.assertIsNone(record.orders)
        self.assertIsNone(record.commission_idr)

        self.db.save_performance_record("snap_partial", record)
        retrieved = self.db.get_performance_record("snap_partial")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.views, 800)
        self.assertIsNone(retrieved.clicks)
        self.assertIsNone(retrieved.orders)
        self.assertIsNone(retrieved.commission_idr)

    # 4. Negative values rejected by model validators
    def test_negative_metrics_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PerformanceRecord(content_id="d1", platform="p1", views=-10)

        with self.assertRaises(ValueError):
            PerformanceRecord(content_id="d1", platform="p1", clicks=-1)

        with self.assertRaises(ValueError):
            PerformanceRecord(content_id="d1", platform="p1", orders=-5)

        with self.assertRaises(ValueError):
            PerformanceRecord(content_id="d1", platform="p1", commission_idr=-1000.0)

        with self.assertRaises(ValueError):
            PerformanceRecord(content_id="", platform="p1")

        with self.assertRaises(ValueError):
            PerformanceRecord(content_id="d1", platform="   ")

    # 5. Conversion rate calculation invariants
    def test_conversion_rates_zero_and_none_denominators(self) -> None:
        # Case A: Views=0, Clicks=0 -> CTR is None (denominator 0), Click-to-Order is None
        rates_zero = calculate_conversion_rates(views=0, clicks=0, orders=0, commission_idr=0.0)
        self.assertIsNone(rates_zero.ctr)
        self.assertIsNone(rates_zero.click_to_order)
        self.assertIsNone(rates_zero.commission_per_order)

        # Case B: Views=100, Clicks=0 -> CTR is 0.0%, Click-to-Order is None (clicks=0)
        rates_no_clicks = calculate_conversion_rates(views=100, clicks=0, orders=0)
        self.assertEqual(rates_no_clicks.ctr, 0.0)
        self.assertIsNone(rates_no_clicks.click_to_order)

        # Case C: Views=None, Clicks=10 -> CTR is None (views unknown)
        rates_unknown_views = calculate_conversion_rates(views=None, clicks=10, orders=2)
        self.assertIsNone(rates_unknown_views.ctr)
        self.assertEqual(rates_unknown_views.click_to_order, 20.0)

        # Case D: Normal valid calculation
        # Views=1000, Clicks=50 (CTR=5.0%), Orders=5 (CR=10.0%), Commission=50,000 (CPO=10,000)
        rates_normal = calculate_conversion_rates(views=1000, clicks=50, orders=5, commission_idr=50000.0)
        self.assertEqual(rates_normal.ctr, 5.0)
        self.assertEqual(rates_normal.click_to_order, 10.0)
        self.assertEqual(rates_normal.commission_per_order, 10000.0)
        self.assertEqual(rates_normal.commission_per_click, 1000.0)

    # 6. Discrepancy warnings (clicks > views or orders > clicks) without crashing
    def test_discrepancy_warnings_generated(self) -> None:
        # Clicks > views
        warnings_clicks = check_metric_anomalies(views=100, clicks=150, orders=5)
        self.assertEqual(len(warnings_clicks), 1)
        self.assertIn("melebihi jumlah tayangan", warnings_clicks[0])

        # Orders > clicks
        warnings_orders = check_metric_anomalies(views=500, clicks=10, orders=25)
        self.assertEqual(len(warnings_orders), 1)
        self.assertIn("melebihi jumlah klik", warnings_orders[0])

        # No discrepancy
        warnings_clean = check_metric_anomalies(views=500, clicks=20, orders=2)
        self.assertEqual(len(warnings_clean), 0)

    # 7. Summary aggregation NEVER double-counts cumulative counters
    def test_summary_never_double_counts_cumulative_snapshots(self) -> None:
        """Crucial invariant: repeated cumulative snapshots of the same content must not be summed."""
        t1 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)

        # Content A has 3 snapshots over 3 days (views grew: 100 -> 250 -> 300)
        recs = [
            PerformanceRecord(id="s1", content_id="post_A", platform="Shopee Video", observed_at=t1, views=100, clicks=5, orders=1, commission_idr=2000.0),
            PerformanceRecord(id="s2", content_id="post_A", platform="Shopee Video", observed_at=t2, views=250, clicks=12, orders=3, commission_idr=6000.0),
            PerformanceRecord(id="s3", content_id="post_A", platform="Shopee Video", observed_at=t3, views=300, clicks=15, orders=4, commission_idr=8000.0),
            # Content B has 1 snapshot (views=50)
            PerformanceRecord(id="s4", content_id="post_B", platform="Shopee Video", observed_at=t2, views=50, clicks=2, orders=0, commission_idr=0.0),
        ]

        summary = calculate_performance_summary(recs)

        self.assertEqual(summary.total_content_items, 2)
        self.assertEqual(summary.total_snapshots, 4)

        # Total views must be 300 (post_A latest) + 50 (post_B latest) = 350.
        # NEVER (100 + 250 + 300 + 50 = 700)!
        self.assertEqual(summary.total_views, 350)
        # Total clicks: 15 + 2 = 17
        self.assertEqual(summary.total_clicks, 17)
        # Total orders: 4 + 0 = 4
        self.assertEqual(summary.total_orders, 4)
        # Total commission: 8000.0 + 0.0 = 8000.0
        self.assertEqual(summary.total_commission_idr, 8000.0)

        # Aggregate CTR: (17 / 350) * 100 = 4.857...
        self.assertAlmostEqual(summary.aggregate_rates.ctr, (17 / 350) * 100.0, places=2)

        # Check item deltas for post_A (t3 vs t1: views 300 - 100 = 200)
        item_a = next(i for i in summary.items if i.content_id == "post_A")
        self.assertEqual(item_a.views_delta, 200)
        self.assertEqual(item_a.clicks_delta, 10)
        self.assertEqual(item_a.orders_delta, 3)
        self.assertEqual(item_a.commission_delta, 6000.0)

    # 8. Filter by content_id, platform, and date range
    def test_filter_by_content_platform_and_date_range(self) -> None:
        t1 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)

        self.db.save_performance_record("rec_1", PerformanceRecord(content_id="post_1", platform="Shopee Video", observed_at=t1, views=100))
        self.db.save_performance_record("rec_2", PerformanceRecord(content_id="post_1", platform="TikTok", observed_at=t2, views=200))
        self.db.save_performance_record("rec_3", PerformanceRecord(content_id="post_2", platform="Shopee Video", observed_at=t3, views=300))

        # Filter content_id
        res_post1 = self.db.list_performance_records(content_id="post_1")
        self.assertEqual(len(res_post1), 2)

        # Filter platform
        res_tiktok = self.db.list_performance_records(platform="TikTok")
        self.assertEqual(len(res_tiktok), 1)
        self.assertEqual(res_tiktok[0].id, "rec_2")

        # Filter date range (t2 to t3)
        res_date = self.db.list_performance_records(start_date=t2, end_date=t3)
        self.assertEqual(len(res_date), 2)
        ids = [r.id for r in res_date]
        self.assertIn("rec_2", ids)
        self.assertIn("rec_3", ids)

    # 9. Duplicate snapshot ID handling: raises ValueError unless allow_overwrite=True
    def test_duplicate_record_id_handling(self) -> None:
        r1 = PerformanceRecord(content_id="post_dup", platform="Shopee Video", views=100, clicks=5)
        self.db.save_performance_record("snap_unique_id", r1)

        # By default, duplicate snapshot ID must be rejected to protect historical immutability
        r2 = PerformanceRecord(content_id="post_dup", platform="Shopee Video", views=150, clicks=8)
        with self.assertRaises(ValueError) as ctx:
            self.db.save_performance_record("snap_unique_id", r2)
        self.assertIn("sudah ada di database", str(ctx.exception))

        # Explicit correction with allow_overwrite=True succeeds
        self.db.save_performance_record("snap_unique_id", r2, allow_overwrite=True)
        history = self.db.list_performance_records(content_id="post_dup")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].views, 150)
        self.assertEqual(history[0].clicks, 8)

    # 10. CLI Smoke Tests: record, show, summary
    def test_cli_performance_record_show_summary_smoke(self) -> None:
        # A. CLI Record
        code_rec = main([
            "performance",
            "record",
            "--content-id",
            "draft_perf_01",
            "--platform",
            "Shopee Video",
            "--views",
            "1000",
            "--clicks",
            "50",
            "--orders",
            "4",
            "--commission",
            "20000.0",
            "--observed-at",
            "2026-11-02T12:00:00Z",
            "--record-id",
            "cli_test_snap_01",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_rec, 0)

        # Verify audit event in database
        events = self.db.list_events()
        perf_event = next((e for e in events if e.module == "performance"), None)
        self.assertIsNotNone(perf_event)
        self.assertEqual(perf_event.action, "record_snapshot")

        # B. CLI Show
        code_show = main([
            "performance",
            "show",
            "--content-id",
            "draft_perf_01",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_show, 0)

        # C. CLI Summary
        code_summary = main([
            "performance",
            "summary",
            "--content-id",
            "draft_perf_01",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_summary, 0)

    # 11. CLI Input Rejection with Non-Zero Exit Code
    def test_cli_rejects_invalid_inputs_with_nonzero_exit_code(self) -> None:
        # Negative views rejected
        code_neg_views = main([
            "performance",
            "record",
            "--content-id",
            "draft_perf_01",
            "--platform",
            "Shopee Video",
            "--views",
            "-50",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_neg_views, 1)

        # Negative commission rejected
        code_neg_comm = main([
            "performance",
            "record",
            "--content-id",
            "draft_perf_01",
            "--platform",
            "Shopee Video",
            "--commission",
            "-1000.0",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_neg_comm, 1)

        # Invalid timestamp rejected
        code_bad_ts = main([
            "performance",
            "record",
            "--content-id",
            "draft_perf_01",
            "--platform",
            "Shopee Video",
            "--observed-at",
            "bukan-tanggal-valid",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_bad_ts, 1)

        # Invalid start date in summary rejected
        code_bad_summary_date = main([
            "performance",
            "summary",
            "--start-date",
            "invalid-start-date",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_bad_summary_date, 1)



    # 12. Non-finite commission values rejected (NaN, Inf, -Inf)
    def test_non_finite_commission_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PerformanceRecord(content_id="d1", platform="p1", commission_idr=float("nan"))
        with self.assertRaises(ValueError):
            PerformanceRecord(content_id="d1", platform="p1", commission_idr=float("inf"))
        with self.assertRaises(ValueError):
            PerformanceRecord(content_id="d1", platform="p1", commission_idr=float("-inf"))

    # 13. Timezone normalization: naive or aware timestamps normalized to UTC
    def test_timezone_normalization(self) -> None:
        from datetime import timezone as dt_tz, timedelta

        # Naive datetime gets UTC timezone attached
        naive_dt = datetime(2026, 11, 2, 8, 30, 0)
        r_naive = PerformanceRecord(content_id="d1", platform="p1", observed_at=naive_dt)
        self.assertIsNotNone(r_naive.observed_at.tzinfo)
        self.assertEqual(r_naive.observed_at.tzinfo, dt_tz.utc)
        self.assertEqual(r_naive.observed_at.hour, 8)

        # Aware datetime (e.g. WIB = UTC+7) is normalized to UTC
        tz_wib = dt_tz(timedelta(hours=7))
        wib_dt = datetime(2026, 11, 2, 17, 0, 0, tzinfo=tz_wib)
        r_wib = PerformanceRecord(content_id="d1", platform="p1", observed_at=wib_dt)
        self.assertEqual(r_wib.observed_at.tzinfo, dt_tz.utc)
        self.assertEqual(r_wib.observed_at.hour, 10)  # 17:00 UTC+7 is 10:00 UTC

    # 14. Identical timestamps resolved with deterministic tie-breaking (id ASC)
    def test_identical_timestamps_deterministic_tiebreak(self) -> None:
        t_same = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
        # Insert snap_b then snap_a with identical observed_at
        self.db.save_performance_record("snap_b", PerformanceRecord(content_id="post_same", platform="Shopee Video", observed_at=t_same, views=200))
        self.db.save_performance_record("snap_a", PerformanceRecord(content_id="post_same", platform="Shopee Video", observed_at=t_same, views=100))

        records = self.db.list_performance_records(content_id="post_same")
        self.assertEqual(len(records), 2)
        # Deterministic order: observed_at ASC, id ASC -> snap_a comes first, snap_b comes second
        self.assertEqual(records[0].id, "snap_a")
        self.assertEqual(records[1].id, "snap_b")

        # In summary, latest snapshot selected is snap_b (views=200)
        summary = calculate_performance_summary(records)
        self.assertEqual(summary.total_views, 200)

    # 15. Conversion rates calculated strictly over cohorts where both metrics are known
    def test_cohort_conversion_rates_partial_unknown(self) -> None:
        t0 = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
        # Item 1: Views=1000, Clicks=50, Orders=None (known views & clicks)
        r1 = PerformanceRecord(content_id="item_1", platform="Shopee Video", observed_at=t0, views=1000, clicks=50, orders=None)
        # Item 2: Views=None, Clicks=20, Orders=2 (known clicks & orders)
        r2 = PerformanceRecord(content_id="item_2", platform="Shopee Video", observed_at=t0, views=None, clicks=20, orders=2)

        summary = calculate_performance_summary([r1, r2])

        # Totals
        self.assertEqual(summary.total_views, 1000)
        self.assertEqual(summary.views_known_count, 1)
        self.assertEqual(summary.views_unknown_count, 1)

        self.assertEqual(summary.total_clicks, 70)
        self.assertEqual(summary.clicks_known_count, 2)
        self.assertEqual(summary.clicks_unknown_count, 0)

        self.assertEqual(summary.total_orders, 2)
        self.assertEqual(summary.orders_known_count, 1)
        self.assertEqual(summary.orders_unknown_count, 1)

        # Strict CTR cohort: Only item_1 has BOTH views and clicks known!
        # CTR must be 50 / 1000 = 5.0%, NOT (50 + 20) / 1000 = 7.0%!
        self.assertEqual(summary.ctr_cohort_count, 1)
        self.assertEqual(summary.aggregate_rates.ctr, 5.0)

        # Strict Click-to-Order cohort: Only item_2 has BOTH clicks and orders known!
        # Click-to-Order must be 2 / 20 = 10.0%, NOT 2 / (50 + 20) = 2.857%!
        self.assertEqual(summary.cr_cohort_count, 1)
        self.assertEqual(summary.aggregate_rates.click_to_order, 10.0)

    # 16. All metrics unknown (None) across all items
    def test_all_metrics_unknown(self) -> None:
        t0 = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
        r = PerformanceRecord(content_id="item_none", platform="Shopee Video", observed_at=t0)
        summary = calculate_performance_summary([r])

        self.assertIsNone(summary.total_views)
        self.assertIsNone(summary.total_clicks)
        self.assertIsNone(summary.total_orders)
        self.assertIsNone(summary.total_commission_idr)
        self.assertEqual(summary.views_unknown_count, 1)
        self.assertEqual(summary.clicks_unknown_count, 1)
        self.assertIsNone(summary.aggregate_rates.ctr)
        self.assertIsNone(summary.aggregate_rates.click_to_order)

    # 17. Recorded true zeros (0 vs None)
    def test_recorded_true_zeros(self) -> None:
        t0 = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
        r = PerformanceRecord(
            content_id="item_zero",
            platform="Shopee Video",
            observed_at=t0,
            views=500,
            clicks=0,
            orders=0,
            commission_idr=0.0,
        )
        summary = calculate_performance_summary([r])

        self.assertEqual(summary.total_views, 500)
        self.assertEqual(summary.total_clicks, 0)
        self.assertEqual(summary.total_orders, 0)
        self.assertEqual(summary.total_commission_idr, 0.0)
        self.assertEqual(summary.clicks_known_count, 1)
        self.assertEqual(summary.clicks_unknown_count, 0)
        # CTR: 0 / 500 = 0.0%
        self.assertEqual(summary.aggregate_rates.ctr, 0.0)
        # Click-to-Order: 0 / 0 -> None (zero denominator)
        self.assertIsNone(summary.aggregate_rates.click_to_order)

    # 18. Date filtering excludes out-of-range snapshots
    def test_summary_date_filtering_excludes_out_of_range(self) -> None:
        t1 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 5, 10, 0, 0, tzinfo=timezone.utc)

        self.db.save_performance_record("snap_early", PerformanceRecord(content_id="post_filter", platform="Shopee Video", observed_at=t1, views=100))
        self.db.save_performance_record("snap_late", PerformanceRecord(content_id="post_filter", platform="Shopee Video", observed_at=t2, views=400))

        # Query only on or after Nov 3
        t_start = datetime(2026, 11, 3, 0, 0, 0, tzinfo=timezone.utc)
        records = self.db.list_performance_records(content_id="post_filter", start_date=t_start)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].id, "snap_late")
        self.assertEqual(records[0].views, 400)

    # 19. Summary period deltas calculated across snapshots in window
    def test_summary_period_delta(self) -> None:
        t1 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 4, 10, 0, 0, tzinfo=timezone.utc)

        r1 = PerformanceRecord(content_id="post_delta", platform="Shopee Video", observed_at=t1, views=100, clicks=10, orders=1, commission_idr=5000.0)
        r2 = PerformanceRecord(content_id="post_delta", platform="Shopee Video", observed_at=t2, views=350, clicks=35, orders=4, commission_idr=20000.0)

        summary = calculate_performance_summary([r1, r2])
        self.assertEqual(len(summary.items), 1)
        item = summary.items[0]
        self.assertEqual(item.views_delta, 250)
        self.assertEqual(item.clicks_delta, 25)
        self.assertEqual(item.orders_delta, 3)
        self.assertEqual(item.commission_delta, 15000.0)

    # 20. CLI performance correct smoke test
    def test_cli_performance_correct_smoke(self) -> None:
        # First record a snapshot
        code_rec = main([
            "performance",
            "record",
            "--content-id",
            "draft_perf_01",
            "--platform",
            "Shopee Video",
            "--views",
            "500",
            "--record-id",
            "snap_to_correct",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_rec, 0)

        # Now correct it using CLI correct
        code_corr = main([
            "performance",
            "correct",
            "--record-id",
            "snap_to_correct",
            "--views",
            "600",
            "--clicks",
            "25",
            "--note",
            "Typo correction in manual record",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_corr, 0)

        # Verify database record updated
        updated = self.db.get_performance_record("snap_to_correct")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.views, 600)
        self.assertEqual(updated.clicks, 25)

        # Verify audit event logged with action="correct_snapshot"
        events = self.db.list_events()
        corr_events = [e for e in events if e.module == "performance" and e.action == "correct_snapshot"]
        self.assertEqual(len(corr_events), 1)
        self.assertIn("snap_to_correct", corr_events[0].note)

    # 21. CLI duplicate record ID fails with non-zero exit code and emits NO audit event
    def test_cli_duplicate_record_id_fails_without_audit_event(self) -> None:
        code1 = main([
            "performance",
            "record",
            "--content-id",
            "draft_perf_01",
            "--platform",
            "Shopee Video",
            "--views",
            "500",
            "--record-id",
            "fixed_id_001",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code1, 0)
        events_before = len([e for e in self.db.list_events() if e.module == "performance"])

        # Attempt to record again with same ID without correct command
        code2 = main([
            "performance",
            "record",
            "--content-id",
            "draft_perf_01",
            "--platform",
            "Shopee Video",
            "--views",
            "800",
            "--record-id",
            "fixed_id_001",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code2, 1)

        # No new audit event should have been logged for the failed record
        events_after = len([e for e in self.db.list_events() if e.module == "performance"])
        self.assertEqual(events_before, events_after)

if __name__ == "__main__":
    unittest.main()
