"""Phase 3.3 specialist-agent and integrated workflow tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from affiliate_factory.agent_context import ExecutionContext
from affiliate_factory.agent_orchestrator import AgentOrchestrator
from affiliate_factory.db import Database
from affiliate_factory.models import Claim, ContentDraft, PerformanceRecord, Product
from affiliate_factory.specialist_agents import (
    AnalyticsAgent,
    ComplianceAgent,
    ContentWriterAgent,
    ExportAgent,
    FactCheckerAgent,
    ResearchAgent,
    build_content_workflow,
    build_specialist_registry,
)
from affiliate_factory.specialist_contracts import (
    AnalyticsInput,
    ComplianceInput,
    ContentWriterInput,
    FactCheckerInput,
    ResearchEvidence,
    ResearchFactInput,
    ResearchInput,
)
from affiliate_factory.workflow_contracts import ApprovalDecision, WorkflowExecutionRequest, WorkflowStatus
from affiliate_factory.workflow_executor import WorkflowExecutor


class TestPhase33Specialists(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db = Database(self.root / "specialists.db")
        self.product = Product(
            id="specialist-product",
            name="Tripod Curated",
            url="https://example.com/tripod-curated",
            price=125000,
            price_observed_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
            notes="Catatan manual tanpa sumber publik langsung.",
        )
        self.context = ExecutionContext(db=self.db)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def research_input(self) -> ResearchInput:
        return ResearchInput(
            product=self.product,
            target_audience="Pembuat konten pemula",
            customer_problems=["video goyang"],
            facts=[
                ResearchFactInput(
                    fact_id="fact-height",
                    text="Tinggi maksimal 1.5m",
                    evidence_ids=["evidence-manual"],
                ),
                ResearchFactInput(
                    fact_id="fact-unsupported",
                    text="Pasti meningkatkan followers",
                    evidence_ids=[],
                ),
            ],
            evidence=[
                ResearchEvidence(
                    evidence_id="evidence-manual",
                    source_ref="manual:product-notes",
                    quote="Tinggi maksimal 1.5m",
                    status="VERIFIED",
                )
            ],
            missing_information=["durability_test"],
        )

    def test_research_preserves_provenance_and_marks_unsupported_or_missing(self) -> None:
        result = ResearchAgent().execute(self.research_input(), self.context)
        self.assertEqual(result.facts[0].classification, "SUPPORTED")
        self.assertEqual(result.facts[0].evidence_ids, ["evidence-manual"])
        self.assertEqual(result.facts[1].classification, "UNSUPPORTED")
        self.assertIn("Pasti meningkatkan followers", result.unsupported_claims)
        self.assertIn("durability_test", result.missing_information)
        self.assertIn("tidak melakukan browsing", result.provenance_note)

    def test_content_writer_uses_only_supported_research_and_manual_fallback(self) -> None:
        research = ResearchAgent().execute(self.research_input(), self.context)
        result = ContentWriterAgent().execute(
            ContentWriterInput(
                draft_id="specialist-draft",
                research=research,
                platform="TikTok",
                content_format="short_video",
            ),
            self.context,
        )
        self.assertIn("Tinggi maksimal 1.5m", result.draft.script)
        self.assertNotIn("Pasti meningkatkan followers", result.draft.script)
        self.assertEqual(result.claim_ids, ["specialist-draft_claim_1"])
        self.assertEqual(self.db.get_draft("specialist-draft", "v1.0").status, "draft")
        self.assertIsNone(self.context.provider)

        empty_research = research.model_copy(update={"facts": [], "evidence": []})
        fallback = ContentWriterAgent().execute(
            ContentWriterInput(draft_id="fallback-draft", research=empty_research, platform="Instagram"),
            self.context,
        )
        self.assertIn("Belum ada fakta produk terverifikasi", fallback.draft.script)

    def test_fact_checker_classifies_supported_unsupported_contradicted_and_manual(self) -> None:
        research = ResearchAgent().execute(self.research_input(), self.context)
        draft = ContentDraft(
            id="fact-draft",
            product_id=self.product.id,
            angle="Evidence-led",
            hook="Hook",
            script="Script",
            caption="#ShopeeAffiliate #KontenAI",
            cta="Lihat detail",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            prompt_version="v1.0",
        )
        claims = [
            Claim(id="supported", draft_id=draft.id, text="Tinggi maksimal 1.5m", source_ref="manual:product-notes"),
            Claim(id="unsupported", draft_id=draft.id, text="Pasti meningkatkan followers"),
            Claim(id="contradicted", draft_id=draft.id, text="Tinggi maksimal 1.5m", source_ref="manual:other"),
        ]
        result = FactCheckerAgent().execute(FactCheckerInput(research=research, draft=draft, claims=claims), self.context)
        classifications = {item.claim_id: item.classification for item in result.findings}
        self.assertEqual(classifications["supported"], "SUPPORTED")
        self.assertEqual(classifications["unsupported"], "UNSUPPORTED")
        self.assertEqual(classifications["contradicted"], "CONTRADICTED")
        self.assertEqual(result.supported_count, 1)
        self.assertEqual(result.unsupported_count, 2)
        self.assertTrue(all(claim.verification_status == "UNVERIFIED" for claim in claims))

    def test_compliance_agent_reuses_fail_closed_engine(self) -> None:
        draft = ContentDraft(
            id="compliance-draft",
            product_id=self.product.id,
            angle="Evidence-led",
            hook="Hook",
            script="Script",
            caption="#ShopeeAffiliate #KontenAI",
            cta="Lihat detail",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            prompt_version="v1.0",
        )
        self.db.insert_product(self.product)
        self.db.upsert_draft(draft)
        result = ComplianceAgent().execute(
            ComplianceInput(
                product=self.product,
                draft=draft,
                config_path=str(self.root / "missing-rules.json"),
            ),
            self.context,
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.report.findings[0].rule_id, "RULE-COMPLIANCE-CONFIG-01")
        self.assertEqual(self.db.get_draft(draft.id, draft.prompt_version).status, "rejected")

    def test_analytics_preserves_missing_metrics_and_empty_data(self) -> None:
        empty = AnalyticsAgent().execute(AnalyticsInput(records=[]), self.context)
        self.assertEqual(empty.total_content_items, 0)
        self.assertIsNone(empty.total_views)
        self.assertTrue(empty.missing_data_notes)

        records = [
            PerformanceRecord(
                id="analytics-1",
                content_id="content-1",
                platform="TikTok",
                views=100,
                clicks=10,
                orders=None,
            ),
            PerformanceRecord(
                id="analytics-2",
                content_id="content-2",
                platform="TikTok",
                views=None,
                clicks=None,
                orders=None,
            ),
        ]
        result = AnalyticsAgent().execute(AnalyticsInput(records=records, platform="TikTok"), self.context)
        self.assertEqual(result.total_content_items, 2)
        self.assertEqual(result.total_views, 100)
        self.assertAlmostEqual(result.aggregate_rates.ctr, 10.0)
        self.assertIsNone(result.aggregate_rates.click_to_order)
        self.assertTrue(any("orders" in note for note in result.missing_data_notes))

    def test_registry_capabilities_and_default_workflow_are_available(self) -> None:
        registry = build_specialist_registry()
        self.assertEqual(registry.get_by_capability("product-research").metadata.agent_id, "specialist.research")
        self.assertEqual(registry.get_by_capability("analytics").metadata.agent_id, "specialist.analytics")
        workflow = build_content_workflow(str(self.root / "missing-rules.json"))
        self.assertEqual(
            [step.step_id for step in workflow.steps],
            ["research", "writer", "fact-check", "compliance", "approval", "export"],
        )

    def test_full_specialist_workflow_pauses_then_approves_and_exports(self) -> None:
        registry = build_specialist_registry()
        executor = WorkflowExecutor(AgentOrchestrator(registry, self.context))
        workflow = build_content_workflow()
        request = WorkflowExecutionRequest(
            execution_id="specialist-workflow",
            workflow_id=workflow.workflow_id,
            input_data={
                "product": self.product.model_dump(mode="json"),
                "target_audience": "Pembuat konten pemula",
                "customer_problems": ["video goyang"],
                "facts": [
                    {
                        "fact_id": "fact-height",
                        "text": "Tinggi maksimal 1.5m",
                        "evidence_ids": ["evidence-manual"],
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": "evidence-manual",
                        "source_ref": "manual:product-notes",
                        "quote": "Tinggi maksimal 1.5m",
                        "status": "VERIFIED",
                    }
                ],
                "draft_id": "specialist-workflow-draft",
                "platform": "Instagram",
                "content_format": "reel",
                "output_dir": str(self.root / "exports"),
            },
            correlation_id="specialist-correlation",
        )
        paused = executor.execute(workflow, request)
        self.assertEqual(paused.status, WorkflowStatus.PAUSED)
        claim_ids = paused.step_results[1].output_data["claim_ids"]
        self.assertEqual(self.db.get_draft("specialist-workflow-draft", "v1.0").status, "waiting_approval")
        self.assertFalse((self.root / "exports").exists())

        approved = executor.resume(
            workflow,
            request.execution_id,
            ApprovalDecision.APPROVE,
            approval_data={
                "human_verified_claim_ids": claim_ids,
                "reviewer_note": "Human reviewed the supplied evidence.",
            },
        )
        self.assertEqual(approved.status, WorkflowStatus.COMPLETED)
        self.assertEqual(self.db.get_draft("specialist-workflow-draft", "v1.0").status, "approved")
        export_output = approved.step_results[-1].output_data
        self.assertTrue(Path(export_output["export_path"]).is_dir())
        self.assertIn("manifest.json", export_output["exported_files"])

    def test_specialist_workflow_rejects_compliance_failure_before_approval(self) -> None:
        registry = build_specialist_registry()
        executor = WorkflowExecutor(AgentOrchestrator(registry, self.context))
        workflow = build_content_workflow(str(self.root / "missing-rules.json"))
        payload = {
            "product": self.product.model_dump(mode="json"),
            "target_audience": "Audience",
            "customer_problems": ["problem"],
            "facts": [],
            "evidence": [],
            "draft_id": "bad-specialist-draft",
            "platform": "TikTok",
            "content_format": "short_video",
            "output_dir": str(self.root / "bad-exports"),
        }
        result = executor.execute(
            workflow,
            WorkflowExecutionRequest(
                execution_id="bad-specialist-workflow",
                workflow_id=workflow.workflow_id,
                input_data=payload,
                correlation_id="bad-specialist-correlation",
            ),
        )
        self.assertEqual(result.status, WorkflowStatus.FAILED)
        self.assertEqual(result.step_results[3].status.value, "completed")
        self.assertEqual(result.step_results[3].output_data["passed"], False)
        self.assertEqual(result.step_results[4].status.value, "failed")

        invalid = payload | {"draft_id": "invalid"}
        with self.assertRaises(ValidationError):
            ResearchInput.model_validate({"product": invalid["product"], "facts": [{"fact_id": "", "text": ""}]})


if __name__ == "__main__":
    unittest.main()
