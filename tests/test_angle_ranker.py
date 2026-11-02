"""Unit tests for AngleRanker and CopywritingAdvisor (Phase 2.2).

Validates empirical aggregation, snapshot deduplication, draft identity mapping,
confidence labeling, platform isolation, and transparent copywriting guidance.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from affiliate_factory.advisor import CopywritingAdvisor
from affiliate_factory.angle_ranker import AngleRanker
from affiliate_factory.cli import main
from affiliate_factory.db import Database
from affiliate_factory.models import ContentDraft, PerformanceRecord, Product


class TestAngleRankerAndAdvisor(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_angles.db"
        self.db = Database(self.db_path)

        # Base product
        self.product = Product(
            id="prod_test_01",
            name="Ring Light 26cm",
            url="https://shopee.co.id/ring-light-26cm",
            price=85000.0,
            price_observed_at=datetime.now(timezone.utc),
            source="manual",
        )
        self.db.insert_product(self.product)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # 1. Aggregate CTR weighted sum clicks and views
    def test_aggregate_ctr_weighted_sum_clicks_and_views(self) -> None:
        draft1 = ContentDraft(
            id="d1", product_id="prod_test_01", angle="Problem-Benefit",
            hook="h1", script="s1", caption="c1", cta="cta1", disclosure_text="#AI", prompt_version="v1.0"
        )
        draft2 = ContentDraft(
            id="d2", product_id="prod_test_01", angle="Problem-Benefit",
            hook="h2", script="s2", caption="c2", cta="cta2", disclosure_text="#AI", prompt_version="v1.0"
        )
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        r1 = PerformanceRecord(content_id="d1", platform="Shopee Video", observed_at=t0, views=1000, clicks=50)
        r2 = PerformanceRecord(content_id="d2", platform="Shopee Video", observed_at=t0, views=2000, clicks=100)

        ranker = AngleRanker()
        report = ranker.rank_angles(records=[r1, r2], drafts=[draft1, draft2], platform="Shopee Video")

        self.assertEqual(len(report.ranked_angles), 1)
        m = report.ranked_angles[0].metrics
        self.assertEqual(m.total_views, 3000)
        self.assertEqual(m.total_clicks, 150)
        # CTR must be (150 / 3000) * 100 = 5.0%
        self.assertAlmostEqual(m.ctr, 5.0, places=2)
        self.assertEqual(m.ctr_cohort_count, 2)

    # 2. Aggregate Click-to-Order weighted sum orders and clicks
    def test_aggregate_click_to_order_weighted_sum_orders_and_clicks(self) -> None:
        draft1 = ContentDraft(
            id="d1", product_id="prod_test_01", angle="Social-Proof",
            hook="h1", script="s1", caption="c1", cta="cta1", disclosure_text="#AI", prompt_version="v1.0"
        )
        draft2 = ContentDraft(
            id="d2", product_id="prod_test_01", angle="Social-Proof",
            hook="h2", script="s2", caption="c2", cta="cta2", disclosure_text="#AI", prompt_version="v1.0"
        )
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        r1 = PerformanceRecord(content_id="d1", platform="Shopee Video", observed_at=t0, views=500, clicks=50, orders=5)
        r2 = PerformanceRecord(content_id="d2", platform="Shopee Video", observed_at=t0, views=1000, clicks=100, orders=10)

        ranker = AngleRanker()
        report = ranker.rank_angles(records=[r1, r2], drafts=[draft1, draft2], platform="Shopee Video")

        self.assertEqual(len(report.ranked_angles), 1)
        m = report.ranked_angles[0].metrics
        self.assertEqual(m.total_clicks, 150)
        self.assertEqual(m.total_orders, 15)
        # CR must be (15 / 150) * 100 = 10.0%
        self.assertAlmostEqual(m.click_to_order, 10.0, places=2)
        self.assertEqual(m.cr_cohort_count, 2)

    # 3. None metrics preserved and never defaulted to 0
    def test_none_metrics_preserved_never_defaulted_to_zero(self) -> None:
        draft = ContentDraft(
            id="d1", product_id="prod_test_01", angle="Unboxing",
            hook="h1", script="s1", caption="c1", cta="cta1", disclosure_text="#AI", prompt_version="v1.0"
        )
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        # views=None, orders=None, commission=None
        r = PerformanceRecord(content_id="d1", platform="Shopee Video", observed_at=t0, clicks=20)

        ranker = AngleRanker()
        report = ranker.rank_angles(records=[r], drafts=[draft], platform="Shopee Video")

        m = report.ranked_angles[0].metrics
        self.assertIsNone(m.total_views)
        self.assertEqual(m.total_clicks, 20)
        self.assertIsNone(m.total_orders)
        self.assertIsNone(m.total_commission_idr)
        self.assertEqual(m.views_unknown_count, 1)
        self.assertIsNone(m.ctr)
        self.assertIsNone(m.click_to_order)

    # 4. Zero denominator yields N/A (None) ratio
    def test_zero_denominator_yields_na_ratio(self) -> None:
        draft = ContentDraft(
            id="d1", product_id="prod_test_01", angle="Features",
            hook="h1", script="s1", caption="c1", cta="cta1", disclosure_text="#AI", prompt_version="v1.0"
        )
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        r = PerformanceRecord(content_id="d1", platform="Shopee Video", observed_at=t0, views=0, clicks=0, orders=0)

        ranker = AngleRanker()
        report = ranker.rank_angles(records=[r], drafts=[draft], platform="Shopee Video")

        m = report.ranked_angles[0].metrics
        self.assertEqual(m.total_views, 0)
        self.assertEqual(m.total_clicks, 0)
        # Denominator zero -> None (N/A), never ZeroDivisionError or 0.0
        self.assertIsNone(m.ctr)
        self.assertIsNone(m.click_to_order)

    # 5. Cumulative snapshots NOT counted as multiple independent contents
    def test_cumulative_snapshots_not_counted_as_multiple_independent_contents(self) -> None:
        draft = ContentDraft(
            id="d_cumul", product_id="prod_test_01", angle="Tutorial",
            hook="h1", script="s1", caption="c1", cta="cta1", disclosure_text="#AI", prompt_version="v1.0"
        )
        t1 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)

        # 3 snapshots of the same content growing over 3 days
        recs = [
            PerformanceRecord(id="s1", content_id="d_cumul", platform="Shopee Video", observed_at=t1, views=100, clicks=5),
            PerformanceRecord(id="s2", content_id="d_cumul", platform="Shopee Video", observed_at=t2, views=250, clicks=12),
            PerformanceRecord(id="s3", content_id="d_cumul", platform="Shopee Video", observed_at=t3, views=300, clicks=15),
        ]

        ranker = AngleRanker()
        report = ranker.rank_angles(records=recs, drafts=[draft], platform="Shopee Video")

        self.assertEqual(report.total_independent_contents, 1)
        m = report.ranked_angles[0].metrics
        self.assertEqual(m.total_contents, 1)
        self.assertEqual(m.total_snapshots, 3)
        # Crucial invariant: latest snapshot (300 views, 15 clicks) is used, NOT sum (100+250+300=650)!
        self.assertEqual(m.total_views, 300)
        self.assertEqual(m.total_clicks, 15)

    # 6. Angle without performance does not get a fake rank
    def test_angle_without_performance_does_not_get_fake_rank(self) -> None:
        draft1 = ContentDraft(
            id="d1", product_id="prod_test_01", angle="Active-Angle",
            hook="h1", script="s1", caption="c1", cta="cta1", disclosure_text="#AI", prompt_version="v1.0"
        )
        draft2 = ContentDraft(
            id="d2", product_id="prod_test_01", angle="Unused-Angle",
            hook="h2", script="s2", caption="c2", cta="cta2", disclosure_text="#AI", prompt_version="v1.0"
        )
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        r1 = PerformanceRecord(content_id="d1", platform="Shopee Video", observed_at=t0, views=500, clicks=20)

        ranker = AngleRanker()
        report = ranker.rank_angles(records=[r1], drafts=[draft1, draft2], platform="Shopee Video")

        # Active angle has rank #1
        self.assertEqual(len(report.ranked_angles), 1)
        self.assertEqual(report.ranked_angles[0].rank, 1)
        self.assertEqual(report.ranked_angles[0].metrics.angle, "Active-Angle")

        # Unused angle must NOT get rank #1 or any numeric rank
        self.assertEqual(len(report.unranked_angles), 1)
        self.assertIsNone(report.unranked_angles[0].rank)
        self.assertEqual(report.unranked_angles[0].metrics.angle, "Unused-Angle")
        self.assertEqual(report.unranked_angles[0].metrics.confidence_label, "TIDAK ADA DATA")

    # 7. Unfound draft excluded from ranking
    def test_unfound_draft_excluded_from_ranking(self) -> None:
        draft = ContentDraft(
            id="d_known", product_id="prod_test_01", angle="Known-Angle",
            hook="h1", script="s1", caption="c1", cta="cta1", disclosure_text="#AI", prompt_version="v1.0"
        )
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        r_known = PerformanceRecord(content_id="d_known", platform="Shopee Video", observed_at=t0, views=100)
        r_orphan = PerformanceRecord(content_id="orphan_draft_99", platform="Shopee Video", observed_at=t0, views=500)

        ranker = AngleRanker()
        report = ranker.rank_angles(records=[r_known, r_orphan], drafts=[draft], platform="Shopee Video")

        self.assertEqual(report.mapped_contents_count, 1)
        self.assertEqual(report.unmapped_contents_count, 1)
        self.assertEqual(report.unmapped_items[0].content_id, "orphan_draft_99")
        self.assertIn("Draft tidak ditemukan", report.unmapped_items[0].reason)

        # Ranked angles must only contain Known-Angle with 1 content
        self.assertEqual(len(report.ranked_angles), 1)
        self.assertEqual(report.ranked_angles[0].metrics.total_contents, 1)
        self.assertEqual(report.ranked_angles[0].metrics.total_views, 100)

    # 8. Draft ID with ambiguous prompt versions is not silently mapped
    def test_ambiguous_prompt_versions_excluded_from_ranking(self) -> None:
        draft_v1 = ContentDraft(
            id="d_multi", product_id="prod_test_01", angle="Angle-A",
            hook="h1", script="s1", caption="c1", cta="cta1", disclosure_text="#AI", prompt_version="v1.0"
        )
        draft_v2 = ContentDraft(
            id="d_multi", product_id="prod_test_01", angle="Angle-B",
            hook="h2", script="s2", caption="c2", cta="cta2", disclosure_text="#AI", prompt_version="v2.0"
        )
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        r = PerformanceRecord(content_id="d_multi", platform="Shopee Video", observed_at=t0, views=1000)

        ranker = AngleRanker()
        report = ranker.rank_angles(records=[r], drafts=[draft_v1, draft_v2], platform="Shopee Video")

        # Crucial invariant: ambiguous version must NOT be mapped to either Angle-A or Angle-B
        self.assertEqual(report.unmapped_contents_count, 1)
        self.assertIn("Versi prompt ambigu", report.unmapped_items[0].reason)
        self.assertEqual(len(report.ranked_angles), 0)

    # 9. Cross-platform data separated by default
    def test_cross_platform_data_separated_by_default(self) -> None:
        draft = ContentDraft(
            id="d1", product_id="prod_test_01", angle="Angle-1",
            hook="h1", script="s1", caption="c1", cta="cta1", disclosure_text="#AI", prompt_version="v1.0"
        )
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        r_shopee = PerformanceRecord(content_id="d1", platform="Shopee Video", observed_at=t0, views=100)
        r_tiktok = PerformanceRecord(content_id="d1", platform="TikTok", observed_at=t0, views=200)

        ranker = AngleRanker()
        # Without specifying platform and allow_cross_platform=False, raises ValueError
        with self.assertRaises(ValueError) as ctx:
            ranker.rank_angles(records=[r_shopee, r_tiktok], drafts=[draft], allow_cross_platform=False)
        self.assertIn("Data lintas platform terdeteksi", str(ctx.exception))

        # Explicit allow_cross_platform=True succeeds and flags report
        report = ranker.rank_angles(records=[r_shopee, r_tiktok], drafts=[draft], allow_cross_platform=True)
        self.assertTrue(report.is_cross_platform)
        self.assertEqual(report.ranked_angles[0].metrics.total_views, 300)

    # 10. Platform filter works correctly
    def test_platform_filter_works_correctly(self) -> None:
        draft = ContentDraft(
            id="d1", product_id="prod_test_01", angle="Angle-1",
            hook="h1", script="s1", caption="c1", cta="cta1", disclosure_text="#AI", prompt_version="v1.0"
        )
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        r_shopee = PerformanceRecord(content_id="d1", platform="Shopee Video", observed_at=t0, views=100)
        r_tiktok = PerformanceRecord(content_id="d1", platform="TikTok", observed_at=t0, views=500)

        ranker = AngleRanker()
        report_shopee = ranker.rank_angles(records=[r_shopee, r_tiktok], drafts=[draft], platform="Shopee Video")
        self.assertEqual(report_shopee.platform, "Shopee Video")
        self.assertEqual(report_shopee.ranked_angles[0].metrics.total_views, 100)

        report_tiktok = ranker.rank_angles(records=[r_shopee, r_tiktok], drafts=[draft], platform="TikTok")
        self.assertEqual(report_tiktok.platform, "TikTok")
        self.assertEqual(report_tiktok.ranked_angles[0].metrics.total_views, 500)

    # 11. Small sample labeled limited evidence
    def test_small_sample_labeled_limited_evidence(self) -> None:
        draft1 = ContentDraft(
            id="d1", product_id="prod_test_01", angle="Small-Sample-Angle",
            hook="h1", script="s1", caption="c1", cta="cta1", disclosure_text="#AI", prompt_version="v1.0"
        )
        draft2 = ContentDraft(
            id="d2", product_id="prod_test_01", angle="Small-Sample-Angle",
            hook="h2", script="s2", caption="c2", cta="cta2", disclosure_text="#AI", prompt_version="v1.0"
        )
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        r1 = PerformanceRecord(content_id="d1", platform="Shopee Video", observed_at=t0, views=100, clicks=10)
        r2 = PerformanceRecord(content_id="d2", platform="Shopee Video", observed_at=t0, views=200, clicks=20)

        ranker = AngleRanker()
        # min_samples=3, but we only have 2 contents
        report = ranker.rank_angles(records=[r1, r2], drafts=[draft1, draft2], platform="Shopee Video", min_samples=3)

        m = report.ranked_angles[0].metrics
        self.assertEqual(m.total_contents, 2)
        self.assertEqual(m.confidence_label, "BUKTI TERBATAS")
        self.assertIn("Sampel hanya 2 konten", m.data_quality_note)

    # 12. Deterministic ranking for identical inputs
    def test_deterministic_ranking_for_identical_inputs(self) -> None:
        drafts = [
            ContentDraft(id=f"d_{i}", product_id="prod_test_01", angle=f"Angle_{i%3}", hook="h", script="s", caption="c", cta="cta", disclosure_text="#AI", prompt_version="v1.0")
            for i in range(6)
        ]
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        recs = [
            PerformanceRecord(content_id=f"d_{i}", platform="Shopee Video", observed_at=t0, views=100 * (i + 1), clicks=5 * (i + 1), orders=i % 2)
            for i in range(6)
        ]

        ranker = AngleRanker()
        report1 = ranker.rank_angles(records=recs, drafts=drafts, platform="Shopee Video")
        report2 = ranker.rank_angles(records=recs, drafts=drafts, platform="Shopee Video")

        self.assertEqual(len(report1.ranked_angles), len(report2.ranked_angles))
        for item1, item2 in zip(report1.ranked_angles, report2.ranked_angles):
            self.assertEqual(item1.rank, item2.rank)
            self.assertEqual(item1.metrics.angle, item2.metrics.angle)
            self.assertEqual(item1.metrics.click_to_order, item2.metrics.click_to_order)

    # 13. CopywritingAdvisor aligns with source metrics
    def test_copywriting_advisor_aligns_with_metrics(self) -> None:
        drafts = [
            ContentDraft(id=f"d_a{i}", product_id="prod_test_01", angle="Proven-Angle", hook="h", script="s", caption="c", cta="cta", disclosure_text="#AI", prompt_version="v1.0")
            for i in range(3)
        ]
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        recs = [
            PerformanceRecord(content_id="d_a0", platform="Shopee Video", observed_at=t0, views=1000, clicks=50, orders=5),
            PerformanceRecord(content_id="d_a1", platform="Shopee Video", observed_at=t0, views=1000, clicks=50, orders=5),
            PerformanceRecord(content_id="d_a2", platform="Shopee Video", observed_at=t0, views=1000, clicks=50, orders=5),
        ]

        ranker = AngleRanker()
        report = ranker.rank_angles(records=recs, drafts=drafts, platform="Shopee Video", min_samples=3)

        advisor = CopywritingAdvisor()
        advice = advisor.advise(report)

        promote_rec = next((r for r in advice.recommendations if r.category == "promote_tested_angle"), None)
        self.assertIsNotNone(promote_rec)
        self.assertEqual(promote_rec.angle, "Proven-Angle")
        self.assertEqual(promote_rec.evidence_strength, "BUKTI CUKUP")
        # Check that observation explicitly cites the exact metrics: 15 orders, 150 clicks, 10.00% CR
        self.assertIn("10.00%", promote_rec.observation)
        self.assertIn("15 pesanan", promote_rec.observation)
        self.assertIn("150 klik", promote_rec.observation)
        self.assertTrue(len(promote_rec.hypothesis_text_suggestions) > 0)

    # 14. Insufficient data yields exploration advice, not a winner claim
    def test_insufficient_data_recommends_exploration_not_winner(self) -> None:
        draft = ContentDraft(
            id="d_single", product_id="prod_test_01", angle="Single-Angle",
            hook="h", script="s", caption="c", cta="cta", disclosure_text="#AI", prompt_version="v1.0"
        )
        t0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        r = PerformanceRecord(content_id="d_single", platform="Shopee Video", observed_at=t0, views=500, clicks=20, orders=2)

        ranker = AngleRanker()
        # min_samples=3, but only 1 sample
        report = ranker.rank_angles(records=[r], drafts=[draft], platform="Shopee Video", min_samples=3)

        advisor = CopywritingAdvisor()
        advice = advisor.advise(report)

        # Must NOT claim a winner via promote_tested_angle
        winner_rec = next((rec for rec in advice.recommendations if rec.category == "promote_tested_angle"), None)
        self.assertIsNone(winner_rec)

        # Must have an explore_insufficient_data recommendation
        explore_rec = next((rec for rec in advice.recommendations if rec.category == "explore_insufficient_data"), None)
        self.assertIsNotNone(explore_rec)
        self.assertEqual(explore_rec.evidence_strength, "BUKTI TERBATAS")
        self.assertIn("Eksplorasi Sampel Diperlukan", explore_rec.headline)

    # 15. CLI smoke test for 'performance angles'
    def test_cli_performance_angles_smoke(self) -> None:
        # Create drafts in database
        for i in range(3):
            self.db.upsert_draft(
                ContentDraft(
                    id=f"cli_d_{i}", product_id=self.product.id, angle="CLI-Angle",
                    hook="h", script="s", caption="c", cta="cta", disclosure_text="#AI", prompt_version="v1.0"
                )
            )
            self.db.save_performance_record(
                f"cli_snap_{i}",
                PerformanceRecord(
                    content_id=f"cli_d_{i}", platform="Shopee Video", views=500, clicks=25, orders=2, commission_idr=10000.0
                ),
            )

        code = main([
            "performance",
            "angles",
            "--platform",
            "Shopee Video",
            "--min-samples",
            "3",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
