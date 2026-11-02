"""CopywritingAdvisor Module.

Generates transparent, evidence-grounded copywriting advice and hypotheses
from AngleRankReport without hallucinating statistical certainty, claiming causality,
promising sales increases, or auto-modifying drafts.
"""

from __future__ import annotations

from affiliate_factory.models import (
    AngleRankReport,
    CopywritingAdviceReport,
    CopywritingRecommendation,
)


class CopywritingAdvisor:
    """Translates empirical angle metrics into practical, transparent copywriting guidance."""

    def advise(self, report: AngleRankReport) -> CopywritingAdviceReport:
        """Produce structured, evidence-backed advice based on angle rankings."""
        recommendations: list[CopywritingRecommendation] = []

        # 1. Check if ANY angle has sufficient evidence
        angles_with_sufficient_proof = [
            item.metrics for item in report.ranked_angles
            if item.metrics.confidence_label == "BUKTI CUKUP"
        ]

        if not angles_with_sufficient_proof:
            # All angles have limited evidence or no ranked angles exist
            if report.ranked_angles:
                recommendations.append(
                    CopywritingRecommendation(
                        category="explore_insufficient_data",
                        angle=None,
                        headline="Eksplorasi Sampel Diperlukan: Belum Ada Angle dengan Bukti Cukup",
                        observation=(
                            f"Seluruh {len(report.ranked_angles)} angle yang diuji memiliki ukuran sampel di bawah "
                            f"ambang batas minimum ({report.min_samples} konten independen per angle). "
                            f"Total konten independen tercatat: {report.mapped_contents_count}."
                        ),
                        actionable_advice=(
                            f"Fokuskan produksi pada pengumpulan observasi tambahan (minimal {report.min_samples} "
                            f"konten independen per angle) sebelum memutuskan angle pemenang atau menghentikan angle tertentu."
                        ),
                        hypothesis_text_suggestions=[],
                        evidence_strength="BUKTI TERBATAS",
                    )
                )
            else:
                recommendations.append(
                    CopywritingRecommendation(
                        category="explore_insufficient_data",
                        angle=None,
                        headline="Tidak Ada Data Performa yang Memenuhi Syarat Pemeringkatan",
                        observation="Belum ada konten independen dengan data metrik terpetakan pada kriteria ini.",
                        actionable_advice="Publikasikan konten yang telah disetujui (APPROVED) dan catat metrik performa awal via CLI.",
                        hypothesis_text_suggestions=[],
                        evidence_strength="TIDAK ADA DATA",
                    )
                )
        else:
            # Promote top angle among those with sufficient evidence
            top_angle = angles_with_sufficient_proof[0]
            cr_str = f"{top_angle.click_to_order:.2f}%" if top_angle.click_to_order is not None else "N/A"
            ctr_str = f"{top_angle.ctr:.2f}%" if top_angle.ctr is not None else "N/A"
            orders_str = f"{top_angle.total_orders:,}" if top_angle.total_orders is not None else "0"
            clicks_str = f"{top_angle.total_clicks:,}" if top_angle.total_clicks is not None else "0"

            hook_suggestions = [
                f"[DRAFT HOOK 1] 'Sering ngalamin kendala saat bikin konten? Angle {top_angle.angle} ini solusinya...'",
                f"[DRAFT HOOK 2] 'Jangan beli produk ini sebelum tahu fitur penting yang satu ini...'",
            ]

            recommendations.append(
                CopywritingRecommendation(
                    category="promote_tested_angle",
                    angle=top_angle.angle,
                    headline=f"Prioritaskan Angle '{top_angle.angle}' untuk Produksi Berkelanjutan",
                    observation=(
                        f"Angle '{top_angle.angle}' mencatat performa konversi Click-to-Order {cr_str} "
                        f"({orders_str} pesanan dari {clicks_str} klik) dan CTR {ctr_str} "
                        f"dengan sampel {top_angle.total_contents} konten independen ({top_angle.confidence_label})."
                    ),
                    actionable_advice=(
                        f"Jadikan angle '{top_angle.angle}' sebagai prioritas utama produksi naskah berikutnya. "
                        f"Eksplorasi variasi hook baru dengan tetap mempertahankan struktur CTA yang sudah terbukti."
                    ),
                    hypothesis_text_suggestions=hook_suggestions,
                    evidence_strength="BUKTI CUKUP",
                )
            )

        # 2. Check Funnel Gap (High CTR but Low CR or 0 Orders)
        for item in report.ranked_angles:
            m = item.metrics
            if m.ctr is not None and m.ctr >= 3.0:
                if m.click_to_order is None or m.click_to_order < 2.0:
                    ctr_val = f"{m.ctr:.2f}%"
                    cr_val = f"{m.click_to_order:.2f}%" if m.click_to_order is not None else "0.00%"
                    cta_suggestions = [
                        "[DRAFT CTA 1] 'Cek spesifikasi lengkap dan harga promo hari ini di keranjang kuning profil.'",
                        "[DRAFT CTA 2] 'Pastikan klaim garansi resmi dan voucher toko sebelum checkout di bio.'",
                    ]
                    recommendations.append(
                        CopywritingRecommendation(
                            category="funnel_gap_high_ctr_low_cr",
                            angle=m.angle,
                            headline=f"Kesenjangan Corong (Funnel Gap) pada Angle '{m.angle}'",
                            observation=(
                                f"Angle '{m.angle}' menarik minat klik dengan CTR {ctr_val}, namun Click-to-Order "
                                f"hanya {cr_val} (pesanan tercatat: {m.total_orders or 0}). "
                                f"Penonton mengklik tautan tetapi tidak menyelesaikan pembelian."
                            ),
                            actionable_advice=(
                                "Evaluasi keselarasan ekspektasi antara narasi video dan informasi produk di Shopee. "
                                "Perjelas kisaran harga dan garansi di bagian narasi agar penonton yang mengklik "
                                "memiliki niat beli yang lebih matang."
                            ),
                            hypothesis_text_suggestions=cta_suggestions,
                            evidence_strength=m.confidence_label,
                        )
                    )

        # 3. Highlight angles with limited evidence when some angles have sufficient evidence
        if angles_with_sufficient_proof:
            limited_angles = [
                item.metrics.angle for item in report.ranked_angles
                if item.metrics.confidence_label == "BUKTI TERBATAS"
            ]
            if limited_angles:
                recommendations.append(
                    CopywritingRecommendation(
                        category="explore_insufficient_data",
                        angle=", ".join(limited_angles),
                        headline="Angle Tambahan dengan Bukti Terbatas",
                        observation=(
                            f"Angle berikut memiliki sampel di bawah batas minimum {report.min_samples}: "
                            f"{', '.join(limited_angles)}."
                        ),
                        actionable_advice=(
                            "Jangan terburu-buru mengabaikan angle ini. Tambahkan minimal beberapa konten independen "
                            "untuk mendapatkan sampel yang cukup sebelum mengambil kesimpulan definitif."
                        ),
                        hypothesis_text_suggestions=[],
                        evidence_strength="BUKTI TERBATAS",
                    )
                )

        # 4. Untested Angles in draft repository
        if report.unranked_angles:
            untested_names = [item.metrics.angle for item in report.unranked_angles]
            recommendations.append(
                CopywritingRecommendation(
                    category="untested_angle",
                    angle=None,
                    headline="Peluang Uji Coba Angle Baru di Repositori",
                    observation=(
                        f"Terdapat {len(untested_names)} angle yang telah didefinisikan dalam draf namun belum memiliki "
                        f"catatan performa pada kriteria ini: {', '.join(untested_names)}."
                    ),
                    actionable_advice=(
                        "Jadwalkan rilis 1-3 konten uji coba untuk angle-angle tersebut guna memperluas variasi "
                        "portofolio konten dan menguji respons audiens."
                    ),
                    hypothesis_text_suggestions=[],
                    evidence_strength="TIDAK ADA DATA",
                )
            )

        # 5. Data Hygiene / Unmapped Items Warning
        if report.unmapped_contents_count > 0:
            reasons = sorted({item.reason for item in report.unmapped_items})
            recommendations.append(
                CopywritingRecommendation(
                    category="data_hygiene",
                    angle=None,
                    headline=f"Peringatan Higienitas Data: {report.unmapped_contents_count} Konten Tidak Terpetakan",
                    observation=(
                        f"Sebanyak {report.unmapped_contents_count} konten independen tidak dapat dipetakan ke angle draf. "
                        f"Penyebab: {'; '.join(reasons)}."
                    ),
                    actionable_advice=(
                        "Periksa kembali kesesuaian content_id pada perintah pencatatan performa dengan ID draf di tabel "
                        "content_drafts dan hindari draf dengan versi prompt ganda yang ambigu."
                    ),
                    hypothesis_text_suggestions=[],
                    evidence_strength="BUKTI TERBATAS",
                )
            )

        disclaimers = [
            "Korelasi metrik historis tidak membuktikan hubungan sebab-akibat (kausalitas).",
            "Hasil pemeringkatan bersifat heuristik deskriptif berdasarkan data empiris yang tercatat, bukan ramalan mutlak masa depan.",
            "Semua saran teks copywriting berstatus DRAFT dan WAJIB ditelaah melalui Review Gate (pemeriksaan klaim dan kepatuhan) serta disetujui manusia sebelum dipublikasikan.",
        ]

        return CopywritingAdviceReport(
            platform=report.platform,
            recommendations=recommendations,
            disclaimers=disclaimers,
        )
