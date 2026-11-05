"""Content Pack Exporter Module.

Exports approved ContentDraft entities into a standardized, atomic distribution pack
under `output/packs/<draft_id>/`.
Enforces strict export gating (draft must be approved with passing compliance).
Guarantees path traversal prevention, explicit collision policy, and atomic staging
so that partial write failures never leave an incomplete pack or a false audit event.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from affiliate_factory.db import Database
from affiliate_factory.models import Event


class ExportGateError(Exception):
    """Raised when export is requested for a draft that does not satisfy the export gate."""
    pass


class ExportCollisionError(Exception):
    """Raised when target content pack directory already exists and overwrite is False."""
    pass


def sanitize_draft_id(draft_id: str) -> str:
    """Validate and sanitize draft ID to prevent path traversal attacks.

    Strictly allows only alphanumeric characters, underscores, and hyphens.
    Rejects '..', path separators ('/', '\\'), null bytes, and empty strings.
    """
    if not draft_id or not isinstance(draft_id, str):
        raise ValueError("Draft ID must be a non-empty string.")

    # Disallow path traversal sequences and separators
    if ".." in draft_id or "/" in draft_id or "\\" in draft_id or "\0" in draft_id:
        raise ValueError(f"Path traversal detected in draft_id: '{draft_id}'.")

    # Strictly allow [A-Za-z0-9_-]
    if not re.match(r"^[A-Za-z0-9_-]+$", draft_id):
        raise ValueError(
            f"Invalid characters in draft_id: '{draft_id}'. "
            f"Only alphanumeric characters, underscores, and hyphens are allowed."
        )

    return draft_id


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 hex digest for a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def export_content_pack(
    db: Database,
    draft_id: str,
    prompt_version: str = "v1.0",
    base_output_dir: Path | str = Path("output") / "packs",
    overwrite: bool = False,
    run_id: str | None = None,
) -> Path:
    """Export an approved ContentDraft to output/packs/<draft_id>/.

    Gating:
    1. Draft must exist and have status == 'approved'.
    2. Compliance report must exist and have passed == True.
    3. Product must exist.

    Safety:
    1. Path traversal prevention on draft_id.
    2. Collision detection (ExportCollisionError unless overwrite=True).
    3. Atomic staging directory: files are written to a temporary staging folder first.
       Only renamed to the final destination once all files are verified.
    4. Audit event emitted only after successful placement.
    """
    effective_run_id = run_id or str(uuid.uuid4())
    safe_draft_id = sanitize_draft_id(draft_id)

    base_dir = Path(base_output_dir).resolve()
    raw_target_dir = base_dir / safe_draft_id

    # Check the unresolved target first so resolve() cannot hide a symlink.
    if raw_target_dir.is_symlink():
        raise ValueError(f"Target path '{raw_target_dir}' is a symlink. Symlinks are not permitted for content packs.")

    target_dir = raw_target_dir.resolve()

    # Path traversal protection via relative_to
    try:
        target_dir.relative_to(base_dir)
    except ValueError:
        raise ValueError(f"Target path '{target_dir}' escapes base directory '{base_dir}'.")

    # 1. Fetch draft and check status
    draft = db.get_draft(draft_id, prompt_version)
    if not draft:
        raise ExportGateError(f"Draft '{draft_id}' (version {prompt_version}) not found in database.")

    if draft.status != "approved":
        raise ExportGateError(
            f"Cannot export draft '{draft_id}' with status '{draft.status}'. "
            f"Only drafts in 'approved' status may be exported."
        )

    # 2. Check compliance report
    comp_report = db.get_compliance_report(draft_id, prompt_version)
    if not comp_report or not comp_report.passed:
        raise ExportGateError(
            f"Cannot export draft '{draft_id}': compliance report missing or failed."
        )

    # 3. Fetch product & claims
    product = db.get_product(draft.product_id)
    if not product:
        raise ExportGateError(f"Product ID '{draft.product_id}' for draft '{draft_id}' not found.")

    claims = db.get_claims_for_draft(draft_id, prompt_version=prompt_version)

    # 4. Atomic staging setup & cleanup of stale staging directories
    base_dir.mkdir(parents=True, exist_ok=True)
    for stale_staging in base_dir.glob(f".staging_{safe_draft_id}_*"):
        if stale_staging.is_dir():
            shutil.rmtree(stale_staging, ignore_errors=True)

    staging_dir = base_dir / f".staging_{safe_draft_id}_{uuid.uuid4().hex[:8]}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    backup_dir: Path | None = None

    try:
        # a. script.md
        script_path = staging_dir / "script.md"
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(f"# Script: {product.name}\n\n")
            f.write(f"**Angle:** {draft.angle}\n\n")
            f.write(f"## Hook (0-3 detik)\n{draft.hook}\n\n")
            f.write(f"## Full Narration / Video Script\n{draft.script}\n\n")
            f.write(f"## Call to Action\n{draft.cta}\n\n")
            f.write(f"## Mandatory Disclosure\n{draft.disclosure_text}\n")

        # b. caption.txt
        caption_path = staging_dir / "caption.txt"
        with open(caption_path, "w", encoding="utf-8") as f:
            f.write(draft.caption)

        # c. hashtags.txt
        # Extract hashtags from caption or disclosure
        hashtags = re.findall(r"#[A-Za-z0-9_]+", f"{draft.caption} {draft.disclosure_text}")
        unique_hashtags = list(dict.fromkeys(hashtags))
        hashtags_path = staging_dir / "hashtags.txt"
        with open(hashtags_path, "w", encoding="utf-8") as f:
            f.write(" ".join(unique_hashtags) + "\n")

        # d. product_info.json (strictly without internal secrets)
        product_info_path = staging_dir / "product_info.json"
        product_data = {
            "id": product.id,
            "name": product.name,
            "url": product.url,
            "price": product.price,
            "price_observed_at": product.price_observed_at.isoformat() if product.price_observed_at else None,
            "source": product.source,
            "notes": product.notes,
        }
        with open(product_info_path, "w", encoding="utf-8") as f:
            json.dump(product_data, f, indent=2, ensure_ascii=False)

        # e. review_checklist.md
        checklist_path = staging_dir / "review_checklist.md"
        with open(checklist_path, "w", encoding="utf-8") as f:
            f.write(f"# Content Pack Review Checklist\n\n")
            f.write(f"- **Draft ID:** `{draft.id}` (v{draft.prompt_version})\n")
            f.write(f"- **Product:** {product.name} (`{product.id}`)\n")
            f.write(f"- **Product URL:** {product.url}\n")
            f.write(f"- **Status:** `{draft.status}`\n")
            f.write(f"- **Exported At:** {datetime.now(timezone.utc).isoformat()}\n\n")

            f.write(f"## 1. Compliance Audit Summary\n")
            f.write(f"- **Compliance Status:** {'PASSED' if comp_report.passed else 'FAILED'}\n")
            if comp_report.findings:
                for f_item in comp_report.findings:
                    f.write(f"  - [{f_item.severity}] [{f_item.rule_id}] {f_item.message}\n")
            else:
                f.write(f"  - No compliance findings recorded.\n")
            f.write("\n")

            f.write(f"## 2. Product Information & Verified Details\n")
            f.write(f"- **Observed Price:** Rp {product.price:,.0f} (At {product.price_observed_at})\n" if product.price else "- **Observed Price:** Tidak diketahui / tidak tercatat\n")
            f.write(f"- **Notes / Unverified Warnings:** {product.notes or '(Tidak ada catatan tambahan)'}\n\n")

            f.write(f"## 3. Claims Verification Record\n")
            if claims:
                for c in claims:
                    f.write(f"- [{c.verification_status}] **\"{c.text}\"**\n")
                    f.write(f"  - Source Ref: `{c.source_ref or 'None'}`\n")
            else:
                f.write(f"- (Tidak ada klaim spesifik yang dicatat)\n")
            f.write("\n")

            f.write(f"> **CATATAN BUKTI SUMBER:**\n")
            f.write(f"> Keberadaan URL sumber dicatat untuk memudahkan verifikasi manusia. "
                    f"Sistem tidak menyatakan bahwa URL sumber secara otomatis membuktikan "
                    f"kebenaran faktual tanpa pemeriksaan independen oleh manusia.\n")

        # f. manifest.json
        manifest_path = staging_dir / "manifest.json"
        exported_files = [
            "script.md",
            "caption.txt",
            "hashtags.txt",
            "product_info.json",
            "review_checklist.md",
        ]
        file_hashes = {}
        for fname in exported_files:
            fpath = staging_dir / fname
            file_hashes[fname] = {
                "sha256": compute_file_sha256(fpath),
                "bytes": fpath.stat().st_size,
            }

        manifest_data = {
            "draft_id": draft.id,
            "prompt_version": draft.prompt_version,
            "product_id": product.id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "status": "APPROVED_AND_EXPORTED",
            "files": file_hashes,
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        # 5. Collision & Idempotency check
        if target_dir.exists():
            if not overwrite:
                # Idempotent export check: verify manifest metadata and core content hashes
                is_identical = False
                target_manifest_path = target_dir / "manifest.json"
                if target_manifest_path.exists():
                    try:
                        with open(target_manifest_path, "r", encoding="utf-8") as mf:
                            existing_manifest = json.load(mf)
                        if (
                            isinstance(existing_manifest, dict)
                            and existing_manifest.get("draft_id") == draft.id
                            and existing_manifest.get("prompt_version") == draft.prompt_version
                            and existing_manifest.get("product_id") == product.id
                        ):
                            core_files = ["script.md", "caption.txt", "hashtags.txt", "product_info.json"]
                            hashes_match = True
                            for cf in core_files:
                                tf = target_dir / cf
                                sf = staging_dir / cf
                                if not tf.exists() or compute_file_sha256(tf) != compute_file_sha256(sf):
                                    hashes_match = False
                                    break
                            if hashes_match:
                                is_identical = True
                    except Exception:
                        is_identical = False

                if is_identical:
                    # Clean up staging directory and return existing pack idempotently
                    shutil.rmtree(staging_dir, ignore_errors=True)
                    db.append_event(
                        Event(
                            id=str(uuid.uuid4()),
                            ts=datetime.now(timezone.utc),
                            run_id=effective_run_id,
                            module="exporter",
                            action="export_pack",
                            status="succeeded",
                            ref_type="draft_id",
                            ref_id=draft.id,
                            note=f"Exported approved content pack to {target_dir} (idempotent match)",
                        )
                    )
                    return target_dir
                else:
                    raise ExportCollisionError(
                        f"Content pack directory '{target_dir}' already exists with conflicting content. "
                        f"Specify overwrite=True or --overwrite to replace it."
                    )

        # 6. Atomic move to target_dir with safe backup and rollback
        if target_dir.exists() and overwrite:
            backup_dir = base_dir / f".backup_{safe_draft_id}_{uuid.uuid4().hex[:8]}"
            target_dir.rename(backup_dir)
            try:
                staging_dir.rename(target_dir)
            except Exception:
                if backup_dir.exists() and not target_dir.exists():
                    backup_dir.rename(target_dir)
                raise
            shutil.rmtree(backup_dir, ignore_errors=True)
        else:
            staging_dir.rename(target_dir)

    except Exception:
        # Clean up staging directory and restore backup on any error
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if backup_dir and backup_dir.exists() and not target_dir.exists():
            backup_dir.rename(target_dir)
        raise

    # 7. Record export event ONLY after successful atomic placement
    db.append_event(
        Event(
            id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            run_id=effective_run_id,
            module="exporter",
            action="export_pack",
            status="succeeded",
            ref_type="draft_id",
            ref_id=draft.id,
            note=f"Exported approved content pack to {target_dir}",
        )
    )

    return target_dir
