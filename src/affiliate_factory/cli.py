"""CLI Interface for AI Affiliate Content Factory.

Provides command-line commands for product intake, deterministic prompt generation,
AI draft import with pipeline verification, draft inspection, human review gate,
and atomic content pack export.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from affiliate_factory.db import DEFAULT_DB_PATH, Database
from affiliate_factory.exporter import (
    ExportCollisionError,
    ExportGateError,
    export_content_pack,
)
from affiliate_factory.intake import intake_product
from affiliate_factory.llm import ManualPaste
from affiliate_factory.models import Product
from affiliate_factory.orchestrator import run_pipeline
from affiliate_factory.prompting import build_copywriting_prompt, parse_and_validate_ai_draft
from affiliate_factory.review import ReviewError, approve_draft, reject_draft, review_claim


def cmd_intake(args: argparse.Namespace) -> int:
    """Execute product intake from a JSON file into SQLite database."""
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"[ERROR] Berkas tidak ditemukan: {file_path}", file=sys.stderr)
        return 1

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as e:
        print(f"[ERROR] Gagal membaca JSON dari {file_path}: {e}", file=sys.stderr)
        return 1

    items: list[dict] = []
    if isinstance(raw_data, list):
        items = raw_data
    elif isinstance(raw_data, dict):
        items = [raw_data]
    else:
        print(f"[ERROR] Konten JSON harus berupa objek atau daftar objek.", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db = Database(db_path)

    ingested_count = 0
    duplicate_count = 0
    error_count = 0

    print(f"Memproses {len(items)} produk ke database ({db_path})...\n")

    for idx, item in enumerate(items, start=1):
        try:
            prod = Product.model_validate(item)
        except Exception as e:
            print(f"[{idx}] [VALIDATION_ERROR] Produk tidak valid: {e}", file=sys.stderr)
            error_count += 1
            continue

        try:
            _, created = intake_product(db, prod)
            if created:
                print(f"[{idx}] [BARU] '{prod.name}' (ID: {prod.id}) berhasil disimpan.")
                ingested_count += 1
            else:
                print(f"[{idx}] [DUPLIKAT] URL '{prod.url}' sudah ada di database. Dilewati tanpa duplikasi.")
                duplicate_count += 1
        except Exception as e:
            print(f"[{idx}] [INTAKE_ERROR] Gagal menyimpan produk ID '{prod.id}': {e}", file=sys.stderr)
            error_count += 1

    print("\n--- RINGKASAN INTAKE PRODUK ---")
    print(f"Total Item Dibaca : {len(items)}")
    print(f"Produk Baru Masuk : {ingested_count}")
    print(f"Duplikat Dilewati : {duplicate_count}")
    print(f"Kesalahan / Error : {error_count}")

    if error_count > 0 and ingested_count == 0 and duplicate_count == 0:
        return 1
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    """Generate deterministic copywriting prompt for a product."""
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db = Database(db_path)

    product = None
    if args.product_id:
        product = db.get_product(args.product_id)
    elif args.product_url:
        product = db.get_product_by_url(args.product_url)

    if not product:
        target = args.product_id or args.product_url or "unknown"
        print(f"[ERROR] Produk '{target}' tidak ditemukan di database ({db_path}).", file=sys.stderr)
        return 1

    prompt = build_copywriting_prompt(
        product=product,
        angle=args.angle or "Problem-Benefit",
        prompt_version=args.version or "v1.0",
    )

    if args.interactive:
        adapter = ManualPaste()
        pasted_output = adapter.generate(prompt)
        if not pasted_output.strip():
            print("[INFO] Tidak ada teks yang ditempelkan. Selesai.")
            return 0
        try:
            draft, claims = parse_and_validate_ai_draft(
                raw_output=pasted_output,
                product_id=product.id,
                prompt_version=args.version or "v1.0",
            )
            res = run_pipeline(db=db, product=product, draft=draft, claims=claims)
            print("\n[SUKSES] Draft berhasil diimpor dan diproses melalui pipeline!")
            print(f"Draft ID : {res.draft.id}")
            print(f"Status   : {res.draft.status} (Menunggu persetujuan manusia)")
            print(f"Kepatuhan: {'LOLOS' if res.compliance_report.passed else 'GAGAL'}")
        except Exception as e:
            print(f"[ERROR] Gagal memvalidasi output AI yang ditempel: {e}", file=sys.stderr)
            return 1
    else:
        print(prompt)

    return 0


def cmd_import_draft(args: argparse.Namespace) -> int:
    """Import and validate structured AI draft JSON, then run pipeline."""
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"[ERROR] Berkas draf tidak ditemukan: {file_path}", file=sys.stderr)
        return 1

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
    except Exception as e:
        print(f"[ERROR] Gagal membaca berkas {file_path}: {e}", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db = Database(db_path)

    product = db.get_product(args.product_id)
    if not product:
        print(f"[ERROR] Produk ID '{args.product_id}' tidak ditemukan di database ({db_path}).", file=sys.stderr)
        return 1

    try:
        draft, claims = parse_and_validate_ai_draft(
            raw_output=raw_text,
            product_id=product.id,
            draft_id=args.draft_id,
            prompt_version=args.version or "v1.0",
        )
    except Exception as e:
        print(f"[VALIDATION_ERROR] Draf AI tidak valid: {e}", file=sys.stderr)
        return 1

    res = run_pipeline(db=db, product=product, draft=draft, claims=claims)

    print("\n--- HASIL PIPELINE DRAFT KONTEN ---")
    print(f"Draft ID         : {res.draft.id}")
    print(f"Produk           : {product.name} ({product.id})")
    print(f"Status Akhir     : {res.draft.status}")
    print(f"Kepatuhan Passed : {res.compliance_report.passed}")

    if res.compliance_report.findings:
        print("\nTemuan Kepatuhan:")
        for f in res.compliance_report.findings:
            print(f"  - [{f.severity}] [{f.rule_id}] {f.message}")

    if res.claims:
        print("\nStatus Klaim:")
        for c in res.claims:
            src = f" (Sumber: {c.source_ref})" if c.source_ref else " (Tanpa Sumber)"
            print(f"  - [{c.verification_status}] '{c.text}'{src}")

    print("\n[CATATAN] Pipeline BERHENTI pada status 'waiting_approval'. Persetujuan manusia mutlak diperlukan.")
    return 0 if res.compliance_report.passed else 1


def cmd_review_show(args: argparse.Namespace) -> int:
    """Display draft content, compliance report, and claims for human review."""
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db = Database(db_path)

    draft = db.get_draft(args.draft_id, args.version or "v1.0")
    if not draft:
        print(f"[ERROR] Draft ID '{args.draft_id}' (versi {args.version or 'v1.0'}) tidak ditemukan.", file=sys.stderr)
        return 1

    comp_report = db.get_compliance_report(args.draft_id, args.version or "v1.0")
    claims = db.get_claims_for_draft(args.draft_id, prompt_version=args.version or 'v1.0')

    print("\n=== DETAIL CONTENT DRAFT ===")
    print(f"ID             : {draft.id}")
    print(f"Product ID     : {draft.product_id}")
    print(f"Prompt Version : {draft.prompt_version}")
    print(f"Status         : {draft.status}")
    print(f"Hook           : {draft.hook}")
    print(f"Script         : {draft.script}")
    print(f"Caption        : {draft.caption}")
    print(f"CTA            : {draft.cta}")
    print(f"Disclosure     : {draft.disclosure_text}")

    print("\n=== LAPORAN KEPATUHAN ===")
    if comp_report:
        print(f"Status Kepatuhan : {'LOLOS (PASSED)' if comp_report.passed else 'TIDAK LOLOS (FAILED)'}")
        for f in comp_report.findings:
            print(f"  - [{f.severity}] [{f.rule_id}] {f.message}")
    else:
        print("Belum ada laporan kepatuhan.")

    print("\n=== STATUS KLAIM ===")
    if claims:
        for c in claims:
            src = f" (Sumber: {c.source_ref})" if c.source_ref else " (Tanpa Sumber)"
            print(f"  - [{c.verification_status}] ID: {c.id} | '{c.text}'{src}")
    else:
        print("Tidak ada klaim spesifik tercatat.")

    print("\n[PERINTAH PENELAAHAN MANUSIA]")
    print(f"  - Telaah Klaim : python -m affiliate_factory.cli review claim --claim-id <id> --status VERIFIED")
    print(f"  - Setujui Draft: python -m affiliate_factory.cli review approve --draft-id {draft.id}")
    print(f"  - Tolak Draft  : python -m affiliate_factory.cli review reject --draft-id {draft.id} --reason \"<alasan>\"")
    return 0


def cmd_review_claim(args: argparse.Namespace) -> int:
    """Review an individual claim, marking it VERIFIED or REJECTED."""
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db = Database(db_path)
    try:
        claim = review_claim(
            db=db,
            claim_id=args.claim_id,
            status=args.status,
            reviewer_note=args.note,
            expected_prompt_version=getattr(args, "version", None),
        )
        print(f"\n[SUKSES] Klaim '{claim.id}' berhasil ditelaah manusia.")
        print(f"Status Baru : {claim.verification_status}")
        print(f"Teks Klaim  : {claim.text}")
        print(f"Rujukan     : {claim.source_ref or 'None'}")
        return 0
    except ReviewError as e:
        print(f"[REVIEW_ERROR] Telaah klaim gagal: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR] Gagal menelaah klaim: {e}", file=sys.stderr)
        return 1


def cmd_review_approve(args: argparse.Namespace) -> int:
    """Approve a draft currently in 'waiting_approval'."""
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db = Database(db_path)
    try:
        draft = approve_draft(
            db=db,
            draft_id=args.draft_id,
            prompt_version=args.version or "v1.0",
            reviewer_note=args.note,
        )
        print(f"\n[SUKSES] Draft '{draft.id}' (v{draft.prompt_version}) berhasil disetujui (APPROVED).")
        print("Draft sekarang memenuhi syarat untuk diekspor via 'export' command.")
        return 0
    except ReviewError as e:
        print(f"[REVIEW_GATE_ERROR] Persetujuan ditolak: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR] Gagal memproses persetujuan: {e}", file=sys.stderr)
        return 1


def cmd_review_reject(args: argparse.Namespace) -> int:
    """Reject a draft in 'waiting_approval' with a mandatory reason."""
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db = Database(db_path)
    try:
        draft = reject_draft(
            db=db,
            draft_id=args.draft_id,
            reason=args.reason,
            prompt_version=args.version or "v1.0",
        )
        print(f"\n[SUKSES] Draft '{draft.id}' (v{draft.prompt_version}) telah ditolak (REJECTED).")
        print(f"Alasan: {args.reason}")
        return 0
    except ReviewError as e:
        print(f"[REVIEW_GATE_ERROR] Penolakan gagal: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR] Gagal memproses penolakan: {e}", file=sys.stderr)
        return 1


def cmd_export(args: argparse.Namespace) -> int:
    """Export an approved ContentDraft to output/packs/<draft_id>/."""
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db = Database(db_path)
    try:
        out_dir = export_content_pack(
            db=db,
            draft_id=args.draft_id,
            prompt_version=args.version or "v1.0",
            base_output_dir=Path(args.output_dir) if args.output_dir else Path("output") / "packs",
            overwrite=args.overwrite,
        )
        print(f"\n[SUKSES] Paket konten berhasil diekspor ke: {out_dir}")
        print("Berkas yang diekspor:")
        print("  - script.md")
        print("  - caption.txt")
        print("  - hashtags.txt")
        print("  - product_info.json")
        print("  - review_checklist.md")
        print("  - manifest.json")
        return 0
    except (ExportGateError, ExportCollisionError, ValueError) as e:
        print(f"[EXPORT_ERROR] Ekspor gagal: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR] Terjadi kesalahan tak terduga saat ekspor: {e}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="affiliate_factory",
        description="AI Affiliate Content Factory CLI - Windows, hemat biaya, berbasis SQLite & Pydantic.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # 1. intake
    parser_intake = subparsers.add_parser("intake", help="Impor data produk dari berkas JSON ke SQLite.")
    parser_intake.add_argument("--file", "-f", required=True, help="Path ke berkas JSON produk.")
    parser_intake.add_argument("--db", help="Path ke SQLite database (opsional).")
    parser_intake.set_defaults(func=cmd_intake)

    # 2. prompt
    parser_prompt = subparsers.add_parser("prompt", help="Hasilkan template prompt copywriting deterministik.")
    parser_prompt.add_argument("--product-id", "-id", help="ID produk yang sudah ada di database.")
    parser_prompt.add_argument("--product-url", "-url", help="URL produk yang sudah ada di database.")
    parser_prompt.add_argument("--angle", help="Sudut pandang konten (default: Problem-Benefit).")
    parser_prompt.add_argument("--version", default="v1.0", help="Versi prompt (default: v1.0).")
    parser_prompt.add_argument("--interactive", action="store_true", help="Gunakan ManualPaste untuk input interaktif.")
    parser_prompt.add_argument("--db", help="Path ke SQLite database (opsional).")
    parser_prompt.set_defaults(func=cmd_prompt)

    # 3. import-draft
    parser_import = subparsers.add_parser("import-draft", help="Impor dan validasi draf naskah AI lalu jalankan pipeline.")
    parser_import.add_argument("--file", "-f", required=True, help="Path ke berkas JSON draf AI.")
    parser_import.add_argument("--product-id", "-id", required=True, help="ID produk terkait di database.")
    parser_import.add_argument("--draft-id", help="ID draf kustom (opsional).")
    parser_import.add_argument("--version", default="v1.0", help="Versi prompt (default: v1.0).")
    parser_import.add_argument("--db", help="Path ke SQLite database (opsional).")
    parser_import.set_defaults(func=cmd_import_draft)

    # 4. inspect (Alias for review show)
    parser_inspect = subparsers.add_parser("inspect", help="Periksa rincian draf, kepatuhan, dan status klaim di database.")
    parser_inspect.add_argument("--draft-id", required=True, help="ID draf yang ingin diperiksa.")
    parser_inspect.add_argument("--version", default="v1.0", help="Versi prompt (default: v1.0).")
    parser_inspect.add_argument("--db", help="Path ke SQLite database (opsional).")
    parser_inspect.set_defaults(func=cmd_review_show)

    # 5. review (Parent command)
    parser_review = subparsers.add_parser("review", help="Gerbang penelaahan manusia (show, claim, approve, reject).")
    review_subparsers = parser_review.add_subparsers(dest="review_action", required=True)

    # 5a. review show
    r_show = review_subparsers.add_parser("show", help="Tampilkan rincian draf untuk penelaahan manusia.")
    r_show.add_argument("--draft-id", required=True, help="ID draf.")
    r_show.add_argument("--version", default="v1.0", help="Versi prompt (default: v1.0).")
    r_show.add_argument("--db", help="Path ke SQLite database.")
    r_show.set_defaults(func=cmd_review_show)

    # 5b. review claim
    r_claim = review_subparsers.add_parser("claim", help="Telaah klaim individual (VERIFIED / REJECTED).")
    r_claim.add_argument("--claim-id", required=True, help="ID klaim.")
    r_claim.add_argument("--status", choices=["VERIFIED", "REJECTED"], required=True, help="Status penelaahan manusia.")
    r_claim.add_argument("--version", help="Versi prompt yang diasosiasikan dengan klaim (opsional).")
    r_claim.add_argument("--note", help="Catatan bukti penelaahan.")
    r_claim.add_argument("--db", help="Path ke SQLite database.")
    r_claim.set_defaults(func=cmd_review_claim)

    # 5c. review approve
    r_approve = review_subparsers.add_parser("approve", help="Setujui draf konten setelah seluruh klaim diverifikasi.")
    r_approve.add_argument("--draft-id", required=True, help="ID draf.")
    r_approve.add_argument("--version", default="v1.0", help="Versi prompt (default: v1.0).")
    r_approve.add_argument("--note", help="Catatan persetujuan manusia.")
    r_approve.add_argument("--db", help="Path ke SQLite database.")
    r_approve.set_defaults(func=cmd_review_approve)

    # 5d. review reject
    r_reject = review_subparsers.add_parser("reject", help="Tolak draf konten dengan alasan wajib.")
    r_reject.add_argument("--draft-id", required=True, help="ID draf.")
    r_reject.add_argument("--reason", required=True, help="Alasan penolakan.")
    r_reject.add_argument("--version", default="v1.0", help="Versi prompt (default: v1.0).")
    r_reject.add_argument("--db", help="Path ke SQLite database.")
    r_reject.set_defaults(func=cmd_review_reject)

    # 6. export
    parser_export = subparsers.add_parser("export", help="Ekspor paket konten yang telah disetujui (APPROVED).")
    parser_export.add_argument("--draft-id", required=True, help="ID draf yang telah disetujui.")
    parser_export.add_argument("--version", default="v1.0", help="Versi prompt (default: v1.0).")
    parser_export.add_argument("--output-dir", help="Direktori basis ekspor (default: output/packs).")
    parser_export.add_argument("--overwrite", action="store_true", help="Timpa paket jika direktori target sudah ada.")
    parser_export.add_argument("--db", help="Path ke SQLite database.")
    parser_export.set_defaults(func=cmd_export)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
