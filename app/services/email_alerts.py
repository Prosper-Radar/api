"""
Email alert service — powered by Resend.

Sends a rich HTML email when a Tier A deal is scored.
Configured via:
  RESEND_API_KEY   — your Resend API key
  ALERT_EMAIL_TO   — recipient(s), comma-separated
  ALERT_EMAIL_FROM — sender address (must be a verified Resend domain)
"""
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_RESEND_SEND_URL = "https://api.resend.com/emails"


def _tier_color(tier: str) -> str:
    return {"A": "#10b981", "B": "#f59e0b", "C": "#6b7280"}.get(tier, "#6b7280")


def _score_bar(score: float) -> str:
    pct = min(100, max(0, score))
    color = "#10b981" if pct >= 70 else "#f59e0b" if pct >= 45 else "#ef4444"
    return (
        f'<div style="background:#e5e7eb;border-radius:4px;height:8px;width:100%;">'
        f'<div style="background:{color};width:{pct:.0f}%;height:8px;'
        f'border-radius:4px;"></div></div>'
    )


def _render_html(
    parcel: dict,
    score: dict,
    assembly: Optional[dict] = None,
    owner: Optional[dict] = None,
    dashboard_url: str = "https://app.prosperradar.com",
) -> str:
    tier = score.get("tier", "?")
    total = score.get("total", 0)
    address = parcel.get("address", "Unknown address")
    county = parcel.get("county", "").title()
    owner_name = parcel.get("owner_name", "—")
    land_value = parcel.get("land_value", 0)
    lot_sqft = parcel.get("lot_size_sqft", 0)
    zoning = parcel.get("zoning_code", "—")
    parcel_id = parcel.get("id", "")

    # Format land value
    def fmt_usd(v):
        if v >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        elif v >= 1_000:
            return f"${v/1_000:.0f}K"
        return f"${v:,.0f}"

    # Score rows
    score_rows = ""
    metrics = [
        ("Waterfront", score.get("scores", {}).get("waterfront")),
        ("Zoning", score.get("scores", {}).get("zoning")),
        ("Price range", score.get("scores", {}).get("price_range")),
        ("Lot size", score.get("scores", {}).get("lot_size")),
        ("Pop. growth", score.get("scores", {}).get("population_growth")),
        ("Traffic (AADT)", score.get("scores", {}).get("traffic")),
        ("Sale recency", score.get("scores", {}).get("recency")),
    ]
    for label, val in metrics:
        if val is None:
            continue
        score_rows += f"""
        <tr>
          <td style="padding:6px 0;color:#6b7280;font-size:13px;">{label}</td>
          <td style="padding:6px 0;width:140px;">{_score_bar(val)}</td>
          <td style="padding:6px 0 6px 8px;text-align:right;font-size:13px;
                     font-weight:600;color:#111827;">{val:.0f}</td>
        </tr>"""

    # Assembly block
    assembly_block = ""
    if assembly and assembly.get("parcel_count", 1) > 1:
        total_val = assembly.get("total_land_value", 0)
        assembly_block = f"""
        <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;
                    padding:16px;margin-top:16px;">
          <p style="margin:0 0 4px;font-size:12px;color:#15803d;font-weight:600;
                    text-transform:uppercase;letter-spacing:.05em;">
            Assembled Site Detected
          </p>
          <p style="margin:0;font-size:14px;color:#166534;">
            <strong>{assembly['parcel_count']} contiguous parcels</strong>
            owned by the same entity &mdash; combined land value
            <strong>{fmt_usd(total_val)}</strong>
          </p>
        </div>"""

    # Owner block
    owner_block = ""
    if owner:
        officers_html = ""
        for o in (owner.get("officers") or [])[:3]:
            officers_html += (
                f'<li style="margin:2px 0;font-size:12px;color:#374151;">'
                f'{o.get("name","?")} — <em>{o.get("title","")}</em></li>'
            )
        owner_block = f"""
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
                    padding:16px;margin-top:16px;">
          <p style="margin:0 0 8px;font-size:12px;color:#64748b;font-weight:600;
                    text-transform:uppercase;letter-spacing:.05em;">Owner Profile</p>
          <p style="margin:0 0 4px;font-size:13px;color:#1e293b;">
            <strong>{owner.get('entity_type','')}</strong> &bull;
            {owner.get('entity_status','').title()}
          </p>
          {"<ul style='margin:6px 0 0;padding-left:16px;'>" + officers_html + "</ul>"
           if officers_html else ""}
        </div>"""

    return f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Tier A Deal Alert</title></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,
             'Segoe UI',sans-serif;background:#f1f5f9;">
  <div style="max-width:600px;margin:32px auto;background:#fff;border-radius:12px;
              overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.12);">

    <!-- Header -->
    <div style="background:#0f172a;padding:24px 32px;">
      <p style="margin:0;font-size:12px;color:#94a3b8;text-transform:uppercase;
                letter-spacing:.08em;">DealScout &bull; Prosper Group Miami</p>
      <h1 style="margin:8px 0 0;font-size:22px;color:#f8fafc;font-weight:700;">
        Tier {tier} Deal Identified
      </h1>
    </div>

    <!-- Body -->
    <div style="padding:28px 32px;">

      <!-- Score badge -->
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px;">
        <div style="background:{_tier_color(tier)};color:#fff;border-radius:50%;
                    width:56px;height:56px;display:flex;align-items:center;
                    justify-content:center;font-size:22px;font-weight:700;
                    flex-shrink:0;text-align:center;line-height:56px;">
          {total:.0f}
        </div>
        <div>
          <p style="margin:0;font-size:18px;font-weight:700;color:#111827;">{address}</p>
          <p style="margin:4px 0 0;font-size:13px;color:#6b7280;">
            {county} County &bull; {zoning} &bull; {fmt_usd(int(lot_sqft))} sqft
          </p>
        </div>
      </div>

      <!-- Key metrics -->
      <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
        <tr>
          <td style="padding:4px 16px 4px 0;font-size:13px;color:#6b7280;">Land value</td>
          <td style="padding:4px 0;font-size:13px;font-weight:600;color:#111827;">
            {fmt_usd(land_value)}
          </td>
          <td style="padding:4px 16px 4px 24px;font-size:13px;color:#6b7280;">Owner</td>
          <td style="padding:4px 0;font-size:13px;font-weight:600;color:#111827;">
            {owner_name[:40]}
          </td>
        </tr>
      </table>

      <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">

      <!-- Score breakdown -->
      <p style="margin:0 0 12px;font-size:13px;font-weight:600;color:#374151;
                text-transform:uppercase;letter-spacing:.05em;">Score breakdown</p>
      <table style="width:100%;border-collapse:collapse;">
        {score_rows}
      </table>

      {assembly_block}
      {owner_block}

      <!-- CTA -->
      <div style="margin-top:28px;text-align:center;">
        <a href="{dashboard_url}/deals/{parcel_id}"
           style="display:inline-block;background:#0f172a;color:#fff;
                  text-decoration:none;padding:12px 28px;border-radius:8px;
                  font-size:14px;font-weight:600;">
          Open in DealScout &rarr;
        </a>
      </div>

    </div>

    <!-- Footer -->
    <div style="background:#f8fafc;padding:16px 32px;border-top:1px solid #e5e7eb;">
      <p style="margin:0;font-size:11px;color:#9ca3af;text-align:center;">
        DealScout &bull; Prosper Group Miami &bull; Auto-generated alert
      </p>
    </div>
  </div>
</body>
</html>"""


async def send_tier_a_alert(
    api_key: str,
    from_email: str,
    to_emails: list[str],
    parcel: dict,
    score: dict,
    assembly: Optional[dict] = None,
    owner: Optional[dict] = None,
    dashboard_url: str = "https://app.prosperradar.com",
) -> bool:
    """
    Send a Tier A deal alert via Resend.
    Returns True on success, False on any error.
    """
    if not api_key or not to_emails:
        logger.info("Resend not configured — skipping alert for parcel %s",
                    parcel.get("id", "?"))
        return False

    address = parcel.get("address", "Unknown")
    subject = f"🏆 Tier A Deal — {address} ({parcel.get('county','').title()} County)"
    html = _render_html(parcel, score, assembly, owner, dashboard_url)

    payload = {
        "from": from_email,
        "to": to_emails,
        "subject": subject,
        "html": html,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _RESEND_SEND_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
        logger.info("Tier A alert sent for parcel %s to %s", parcel.get("id"), to_emails)
        return True
    except httpx.HTTPStatusError as exc:
        logger.error("Resend HTTP error %s: %s", exc.response.status_code, exc.response.text)
        return False
    except Exception as exc:
        logger.error("Failed to send Tier A alert: %s", exc)
        return False
