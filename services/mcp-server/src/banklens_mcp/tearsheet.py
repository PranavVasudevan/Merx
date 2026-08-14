"""D1 (docs/audit/04-remediation-prompts.md): server-side per-bank PDF
tearsheet — profile, X-Ray, capital, concentration, peer cluster, risk score
and stress results in one document, with the data vintage, source attribution
and the G7 risk disclaimer embedded on every page so an exported PDF carries
the same honesty the live pages do.

Built with reportlab (BSD-licensed, pip-installed — a $0-cost pure-Python
dependency, same category as duckdb/prometheus-client in the bridge image).
"""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from . import data
from .tools import get_bank_profile, get_bank_xray, get_peer_cluster, get_risk_score, run_stress

DISCLAIMER = (
    "Not investment advice. Not a supervisory rating. Not a regulatory capital calculation. "
    "The risk score reflects structural resemblance to past bank failures, not a prediction of failure."
)


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("BLTitle", parent=ss["Title"], fontSize=18, spaceAfter=2))
    ss.add(ParagraphStyle("BLSubtitle", parent=ss["Normal"], textColor=colors.grey, fontSize=9))
    ss.add(ParagraphStyle("BLH2", parent=ss["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4))
    ss.add(ParagraphStyle("BLBody", parent=ss["Normal"], fontSize=9, leading=12))
    ss.add(ParagraphStyle("BLDisclaimer", parent=ss["Normal"], fontSize=7.5, textColor=colors.grey))
    return ss


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    t = Table([[k, v] for k, v in rows], colWidths=[2.3 * inch, 3.8 * inch])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e2e2")),
    ]))
    return t


def _fmt_pct(v) -> str:
    return "—" if v is None else f"{v:.2f}%"


def _fmt_pct_entry(entry: dict | None) -> str:
    if not entry:
        return "—"
    v, p = entry.get("value"), entry.get("percentile")
    base = _fmt_pct(v)
    return f"{base} ({p:.0f}th pctile)" if p is not None else base


def _footer(canvas, doc, *, cert: int, vintage: str):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(0.75 * inch, 0.5 * inch,
                       f"BankLens — CERT {cert} — data vintage {vintage} — page {doc.page}")
    canvas.drawRightString(LETTER[0] - 0.75 * inch, 0.5 * inch, DISCLAIMER[:90] + "…")
    canvas.restoreState()


def build_tearsheet_pdf(cert: int) -> bytes:
    """Renders the tearsheet and returns raw PDF bytes. Raises ValueError for
    an unknown CERT (same as every other per-bank tool)."""
    profile = get_bank_profile(cert)
    xray = get_bank_xray(cert)
    peer = get_peer_cluster(cert)
    try:
        risk = get_risk_score(cert)
    except ValueError as exc:
        risk = {"unavailable": str(exc)}
    try:
        stress = run_stress(cert)
    except ValueError as exc:
        stress = {"unavailable": str(exc)}

    vintage = profile["quarter"]
    ss = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        topMargin=0.75 * inch, bottomMargin=0.85 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )

    story = []
    story.append(Paragraph(profile["name"], ss["BLTitle"]))
    loc = profile.get("state") or profile.get("country") or "—"
    story.append(Paragraph(
        f"CERT {cert} · {loc} · ${profile['assets_b']:.1f}B assets · "
        f"quarter {vintage} · peer cluster: {profile.get('peer_cluster') or '—'}",
        ss["BLSubtitle"],
    ))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Capital", ss["BLH2"]))
    cap = profile["capital"]
    story.append(_kv_table([
        ("CET1 ratio", _fmt_pct_entry(cap["cet1"])),
        ("Tier 1 risk-based capital", _fmt_pct_entry(cap["tier1_rbc"])),
        ("Total risk-based capital", _fmt_pct_entry(cap["total_rbc"])),
        ("Leverage ratio", _fmt_pct_entry(cap["leverage"])),
    ]))

    story.append(Paragraph("Concentration", ss["BLH2"]))
    conc = profile["concentration"]
    story.append(_kv_table([
        ("CRE concentration", _fmt_pct_entry(conc["cre"])),
        ("C&I concentration", _fmt_pct_entry(conc["c_and_i"])),
        ("Residential mortgage", _fmt_pct_entry(conc["residential_mortgage"])),
        ("Consumer", _fmt_pct_entry(conc["consumer"])),
        ("Agricultural", _fmt_pct_entry(conc["agricultural"])),
    ]))

    story.append(Paragraph("Funding", ss["BLH2"]))
    fund = profile["funding"]
    story.append(_kv_table([
        ("Uninsured deposits", _fmt_pct_entry(fund["uninsured_deposit_pct"])),
        ("Loan / deposit ratio", _fmt_pct_entry(fund["loan_to_deposit_pct"])),
        ("Core deposits", _fmt_pct_entry(fund["core_deposit_pct"])),
    ]))

    fp = profile.get("footprint")
    story.append(Paragraph("Branch footprint", ss["BLH2"]))
    if fp:
        story.append(_kv_table([
            ("Branches", str(fp["branch_count"])),
            ("Total branch deposits", f"${fp['total_deposits'] / 1e9:.2f}B" if fp.get("total_deposits") else "—"),
            ("States", ", ".join(fp["states"]) or "—"),
            ("Data vintage (SOD)", str(fp.get("sod_vintage") or "—")),
        ]))
    else:
        story.append(Paragraph("No landed branch footprint for this institution.", ss["BLBody"]))

    story.append(Paragraph("X-Ray flags", ss["BLH2"]))
    flags = xray.get("flags") or []
    if flags:
        rows = [[f.get("severity", "").upper(), f"{f.get('factor', '')}: {f.get('note', '')}"] for f in flags]
        t = Table(rows, colWidths=[0.9 * inch, 5.2 * inch])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No X-Ray flags raised this quarter.", ss["BLBody"]))

    story.append(Paragraph("Peer cluster", ss["BLH2"]))
    story.append(Paragraph(
        f"{peer.get('cluster_label') or '—'} — {peer.get('cluster_size') or 0} member bank(s). "
        f"Sample peers: {', '.join(peer.get('sample_peers') or []) or '—'}.",
        ss["BLBody"],
    ))

    story.append(Paragraph("Deposit-flight risk score", ss["BLH2"]))
    if risk.get("unavailable"):
        story.append(Paragraph(risk["unavailable"], ss["BLBody"]))
    else:
        story.append(_kv_table([
            ("Resemblance percentile", f"{risk.get('resemblance_percentile'):.0f}th" if risk.get("resemblance_percentile") is not None else "—"),
            ("Model trained on", str(risk.get("model_trained_on") or "—")),
        ]))
        story.append(Paragraph(risk.get("note", ""), ss["BLDisclaimer"]))

    story.append(Paragraph("Stress test (3% loan loss / 15% deposit outflow / +200bps rate shock)", ss["BLH2"]))
    if stress.get("unavailable"):
        story.append(Paragraph(stress["unavailable"], ss["BLBody"]))
    else:
        story.append(_kv_table([
            ("CET1 before", _fmt_pct(stress["before"].get("cet1"))),
            ("CET1 after", _fmt_pct(stress["after"].get("cet1"))),
            ("Passes all regulatory minimums", "Yes" if stress.get("passes_all") else "No"),
        ]))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        f"Sources: FDIC BankFind / Call Reports (financials, capital, credit), "
        f"FDIC Summary of Deposits (branch footprint, vintage {fp.get('sod_vintage') if fp else 'n/a'}). "
        "Tiingo market data is excluded from this export (license does not permit redistribution).",
        ss["BLDisclaimer"],
    ))
    story.append(Paragraph(DISCLAIMER, ss["BLDisclaimer"]))

    doc.build(
        [KeepTogether(story[:1])] + story[1:],
        onFirstPage=lambda c, d: _footer(c, d, cert=cert, vintage=vintage),
        onLaterPages=lambda c, d: _footer(c, d, cert=cert, vintage=vintage),
    )
    return buf.getvalue()
