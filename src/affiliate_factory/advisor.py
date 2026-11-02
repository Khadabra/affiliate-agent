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

        # 1. Identify candidate angles with sufficient content sample size
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
                            f"konten independen per angle) sebelum memutuskan angle prioritas atau menghentikan angle tertentu."
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
            top_angle = angles_with_sufficient_proof[0]

            # Invariant: Never promote an angle based on click_to_order if conversion data is unavailable
            if top_angle.click_to_order is None:
                recommendations.append(
                    CopywritingRecommendation(
                        category="explore_insufficient_data",
                        angle=top_angle.angle,
                        headline=f"Eksplorasi Konversi Diperlukan: Angle '{top_angle.angle}' Memiliki Sampel Cukup Namun Konversi Belum Tercatat",
                        observation=(
                            f"Angle '{top_angle.angle}' memiliki {top_angle.total_contents} konten independen "
                            f"({top_angle.confidence_label}), namun data pesanan/konversi (click-to-order) belum tercatat (None). "
                            f"Tingkat konversi belum dapat dinilai."
                        ),
                        actionable_advice=(
                            f"Lengkapi pencatatan metrik pesanan untuk konten pada angle '{top_angle.angle}' sebelum "
                            f"mengambil kesimpulan definitif mengenai efektivitas konversinya."
                        ),
                        hypothesis_text_suggestions=[],
                        evidence_strength="BUKTI TERBATAS",
                    )
                )
            else:
                cr_str = f"{top_angle.click_to_order:.2f}%"
                ctr_str = f"{top_angle.ctr:.2f}%" if top_angle.ctr is not None else "N/A"
                orders_str = f"{top_angle.total_orders:,} pesanan" if top_angle.total_orders is not None else "pesanan tidak diketahui"
                clicks_str = f"{top_angle.total_clicks:,} klik" if top_angle.total_clicks is not None else "klik tidak diketahui"

                hook_suggestions = [
                    f"[DRAFT HOOK 1] 'Menghadapi kendala dalam rutinitas harian? Mari kita tinjau solusi dari angle {top_angle.angle}...'",
                    f"[DRAFT HOOK 2] 'Tiga hal penting yang perlu diperhatikan saat memilih produk pendukung aktivitas Anda...'",
                ]

                recommendations.append(
                    CopywritingRecommendation(
                        category="promote_tested_angle",
                        angle=top_angle.angle,
                        headline=f"Pertimbangkan Angle '{top_angle.angle}' untuk Produksi Berkelanjutan",
                        observation=(
                            f"Angle '{top_angle.angle}' mencatat performa konversi Click-to-Order {cr_str} "
                            f"({orders_str} dari {clicks_str}) dan CTR {ctr_str} "
                            f"dengan sampel {top_angle.total_contents} konten independen ({top_angle.confidence_label})."
                        ),
                        actionable_advice=(
                            f"Jadikan angle '{top_angle.angle}' sebagai salah satu pertimbangan prioritas naskah berikutnya "
                            f"dengan tetap memvalidasi kesesuaian narasi."
                        ),
                        hypothesis_text_suggestions=hook_suggestions,
                        evidence_strength="BUKTI CUKUP",
                    )
                )

        # 2. Check Funnel Gap (High CTR but Low CR or 0 Orders)
        for item in report.ranked_angles:
            m = item.metrics
            if m.ctr is not None and m.ctr >= 3.0:
                if m.click_to_order is not None and m.click_to_order < 2.0:
                    ctr_val = f"{m.ctr:.2f}%"
                    cr_val = f"{m.click_to_order:.2f}%"
                    orders_str = f"{m.total_orders:,} pesanan" if m.total_orders is not None else "pesanan tidak tercatat"
                    cta_suggestions = [
                        "[DRAFT CTA 1] 'Pelajari detail spesifikasi dan kecocokan kebutuhan produk melalui tautan di profil.'",
                        "[DRAFT CTA 2] 'Simak ulasan lengkap dan kesesuaian produk sebelum memutuskan pembelian.'",
                    ]
                    recommendations.append(
                        CopywritingRecommendation(
                            category="funnel_gap_high_ctr_low_cr",
                            angle=m.angle,
                            headline=f"Kesenjangan Corong (Funnel Gap) pada Angle '{m.angle}'",
                            observation=(
                                f"Angle '{m.angle}' menarik minat klik dengan CTR {ctr_val}, namun Click-to-Order "
                                f"tercatat {cr_val} ({orders_str}). "
                                f"Penonton mengklik tautan tetapi tingkat penyelesaian pesanan masih rendah."
                            ),
                            actionable_advice=(
                                "Evaluasi keselarasan narasi konten dengan ekspektasi produk agar penonton yang mengklik "
                                "memiliki pemahaman spesifikasi yang jelas sebelum mempertimbangkan pembelian."
                            ),
                            hypothesis_text_suggestions=cta_suggestions,
                            evidence_strength=m.confidence_label,
                        )
                    )
                elif m.click_to_order is None and m.total_orders is None:
                    recommendations.append(
                        CopywritingRecommendation(
                            category="explore_insufficient_data",
                            angle=m.angle,
                            headline=f"Data Konversi Belum Lengkap untuk CTR Tinggi pada Angle '{m.angle}'",
                            observation=(
                                f"Angle '{m.angle}' memiliki CTR {m.ctr:.2f}%, namun metrik pesanan dan Click-to-Order "
                                f"belum tercatat (None). Tingkat konversi belum dapat dinilai."
                            ),
                            actionable_advice=(
                                "Catat data pesanan untuk konten ini guna memastikan apakah rasio klik yang tinggi "
                                "benar-benar berlanjut ke pembelian."
                            ),
                            hypothesis_text_suggestions=[],
                            evidence_strength="BUKTI TERBATAS",
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
            "Hasil pemeringkatan bersifat heuristik deskriptif berdasarkan data empiris yang tercatat, bukan ramalan mutlak masa depan atau klaim signifikansi statistik.",
            "Semua saran teks copywriting berstatus DRAFT dan WAJIB ditelaah melalui Review Gate (pemeriksaan klaim dan kepatuhan) serta disetujui manusia sebelum dipublikasikan.",
        ]

        return CopywritingAdviceReport(
            platform=report.platform,
            recommendations=recommendations,
            disclaimers=disclaimers,
        )
