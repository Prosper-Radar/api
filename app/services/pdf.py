"""
Deal Memo PDF generator — powered by fpdf2 (pure Python, no system deps).

Layout (A4, ~1 page):
  ┌─────────────────────────────────────────┐
  │ HEADER  — DealScout / Prosper Group     │
  ├─────────────────────────────────────────┤
  │ AERIAL PHOTO  (Mapbox Static API)       │
  ├─────────────────────────────────────────┤
  │ PROPERTY OVERVIEW  |  DEAL SCORE        │
  ├─────────────────────────────────────────┤
  │ OWNER PROFILE       ASSEMBLED SITE      │
  ├─────────────────────────────────────────┤
  │ COMPARABLE SALES (recent, same zoning)  │
  ├─────────────────────────────────────────┤
  │ FOOTER — generated date + model version │
  └─────────────────────────────────────────┘
"""
from __future__ import annotations

import io
import logging
from datetime import date
from typing import Optional

import httpx
from fpdf import FPDF, Align

logger = logging.getLogger(__name__)

# Palette
_DARK   = (15,  23,  42)   # slate-900
_MID    = (71,  85, 105)   # slate-600
_LIGHT  = (248, 250, 252)  # slate-50
_WHITE  = (255, 255, 255)
_GREEN  = (16, 185, 129)   # emerald-500
_AMBER  = (245, 158, 11)   # amber-500
_RED    = (239, 68,  68)   # red-500
_BORDER = (226, 232, 240)  # slate-200

from app.scoring.version import MODEL_VERSION  # noqa: F401  (re-exported for pdf footer)


def _tier_color(tier: str) -> tuple[int, int, int]:
    return {"A": _GREEN, "B": _AMBER, "C": _RED}.get(tier, _MID)


def _fmt_usd(v: Optional[int | float]) -> str:
    if v is None:
        return "—"
    v = float(v)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v:,.0f}"


def _fmt_sqft(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f} sqft"


async def _fetch_aerial_image(
    lon: float,
    lat: float,
    mapbox_token: str,
    width: int = 800,
    height: int = 300,
    zoom: int = 17,
) -> Optional[bytes]:
    """Fetch a satellite aerial image from Mapbox Static API as PNG bytes."""
    if not mapbox_token or lon == 0.0 or lat == 0.0:
        return None
    url = (
        f"https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/static/"
        f"{lon},{lat},{zoom}/{width}x{height}@2x"
        f"?access_token={mapbox_token}"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.content
    except Exception as exc:
        logger.warning("Aerial image fetch failed (%.4f, %.4f): %s", lon, lat, exc)
        return None


class _DealMemoPDF(FPDF):
    """Custom FPDF subclass with DealScout styling."""

    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=12)
        self.set_margins(14, 14, 14)
        self.add_page()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_color(self, rgb: tuple[int, int, int]):
        self.set_fill_color(*rgb)
        self.set_text_color(*rgb)

    def _draw_score_bar(self, x: float, y: float, w: float, score: float,
                        h: float = 3.0):
        """Draw a horizontal score bar (0–100) at the given position."""
        fill = min(100.0, max(0.0, score))
        color = _GREEN if fill >= 70 else _AMBER if fill >= 45 else _RED
        # Background
        self.set_fill_color(*_BORDER)
        self.rect(x, y, w, h, style="F")
        # Filled portion
        self.set_fill_color(*color)
        self.rect(x, y, w * fill / 100, h, style="F")

    def _ascii(self, s: str) -> str:
        """Replace non-latin-1 chars so built-in Helvetica doesn't choke."""
        return (s
                .replace("\u2014", "-")   # em dash
                .replace("\u2013", "-")   # en dash
                .replace("\u2022", "*")   # bullet
                .replace("\u00b7", ".")   # middle dot
                .replace("\u00ae", "(R)")
                .replace("\u00a9", "(c)")
                .replace("\u2019", "'")
                .replace("\u2018", "'")
                .replace("\u201c", '"')
                .replace("\u201d", '"'))

    def _section_title(self, text: str):
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*_MID)
        self.cell(0, 5, text.upper(), ln=True)
        # underline
        y = self.get_y()
        self.set_draw_color(*_BORDER)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(2)

    def _kv(self, label: str, value: str, col_w: float = 40):
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_MID)
        self.cell(col_w, 5, self._ascii(label), ln=False)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*_DARK)
        self.cell(0, 5, self._ascii(value), ln=True)

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def add_header(self, tier: str, total_score: float, address: str, county: str):
        # Dark background strip
        self.set_fill_color(*_DARK)
        self.rect(0, 0, self.w, 22, style="F")
        self.set_y(4)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*_MID)
        self.cell(0, 4, "DEALSCOUT  -  PROSPER GROUP MIAMI", align=Align.C, ln=True)

        # Score badge (right)
        badge_color = _tier_color(tier)
        bx = self.w - self.r_margin - 18
        self.set_fill_color(*badge_color)
        self.ellipse(bx, 5, 16, 14, style="F")
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*_WHITE)
        self.set_xy(bx - 1, 8)
        self.cell(18, 6, f"{total_score:.0f}", align=Align.C, ln=False)

        # Address (left)
        self.set_xy(self.l_margin, 7)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*_WHITE)
        self.cell(self.w - 50, 5, address[:50], ln=True)
        self.set_x(self.l_margin)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(148, 163, 184)  # slate-400
        self.cell(0, 4, f"Tier {tier}  -  {county.title()} County", ln=True)
        self.ln(4)

    def add_aerial(self, image_bytes: Optional[bytes]):
        if image_bytes:
            try:
                img_io = io.BytesIO(image_bytes)
                iw = self.w - self.l_margin - self.r_margin
                self.image(img_io, x=self.l_margin, y=self.get_y(), w=iw, h=45)
                self.ln(47)
                return
            except Exception as exc:
                logger.debug("Could not embed aerial image: %s", exc)
        # Placeholder when no image
        iw = self.w - self.l_margin - self.r_margin
        self.set_fill_color(226, 232, 240)
        self.rect(self.l_margin, self.get_y(), iw, 30, style="F")
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_MID)
        self.set_xy(self.l_margin, self.get_y() + 12)
        self.cell(iw, 5, "Aerial imagery not available", align=Align.C, ln=True)
        self.ln(4)

    def add_property_and_score(self, parcel: dict, score: dict):
        col_w = (self.w - self.l_margin - self.r_margin - 6) / 2
        start_y = self.get_y()

        # LEFT — Property overview
        self._section_title("Property Overview")
        self._kv("Address", (parcel.get("address") or "—")[:38])
        self._kv("Parcel ID", (parcel.get("parcel_id") or "—")[:20])
        self._kv("County", (parcel.get("county") or "—").title())
        self._kv("Zoning", parcel.get("zoning_code") or "—")
        self._kv("Lot size", _fmt_sqft(parcel.get("lot_size_sqft")))
        self._kv("Land value", _fmt_usd(parcel.get("land_value")))
        sale_date = parcel.get("last_sale_date")
        sale_price = parcel.get("last_sale_price")
        if sale_date or sale_price:
            self._kv("Last sale", f"{sale_date or '—'}  @  {_fmt_usd(sale_price)}")
        left_end_y = self.get_y()

        # RIGHT — Score breakdown
        self.set_xy(self.l_margin + col_w + 6, start_y)
        self._section_title("Deal Score")

        scores = score.get("scores", {})
        rows = [
            ("Waterfront",     scores.get("waterfront")),
            ("Zoning",         scores.get("zoning")),
            ("Price range",    scores.get("price_range")),
            ("Lot size",       scores.get("lot_size")),
            ("Pop. growth",    scores.get("population_growth")),
            ("Traffic (AADT)", scores.get("traffic")),
            ("Sale recency",   scores.get("recency") or scores.get("sale_recency")),
        ]
        bar_x = self.l_margin + col_w + 6
        bar_w = col_w - 30

        for label, val in rows:
            if val is None:
                continue
            ry = self.get_y()
            self.set_font("Helvetica", "", 7.5)
            self.set_text_color(*_MID)
            self.set_xy(bar_x, ry)
            self.cell(26, 4.5, label, ln=False)
            self._draw_score_bar(bar_x + 26, ry + 0.8, bar_w, val)
            self.set_font("Helvetica", "B", 7.5)
            self.set_text_color(*_DARK)
            self.set_xy(bar_x + 26 + bar_w + 1, ry)
            self.cell(8, 4.5, f"{val:.0f}", align=Align.R, ln=True)
            self.set_x(bar_x)

        # Total
        self.ln(1)
        self.set_x(bar_x)
        self.set_font("Helvetica", "B", 9)
        tier = score.get("tier", "?")
        self.set_text_color(*_tier_color(tier))
        self.cell(col_w, 5, f"Total  {score.get('total', 0):.1f} / 100  (Tier {tier})", ln=True)

        self.set_y(max(left_end_y, self.get_y()) + 3)

    def add_owner_and_assembly(self, owner: Optional[dict], assembly: Optional[dict]):
        col_w = (self.w - self.l_margin - self.r_margin - 6) / 2
        start_y = self.get_y()

        # LEFT — Owner profile
        self.set_xy(self.l_margin, start_y)
        self._section_title("Owner Profile")
        if owner:
            self._kv("Entity type", owner.get("entity_type") or "—")
            self._kv("Status", owner.get("entity_status") or "—")
            self._kv("Filed", str(owner.get("filing_date") or "—"))
            self._kv("Reg. agent", (owner.get("registered_agent") or "—")[:30])
            officers = owner.get("officers") or []
            if officers:
                self.set_font("Helvetica", "B", 7.5)
                self.set_text_color(*_DARK)
                self.cell(0, 4, "Officers:", ln=True)
                for o in officers[:3]:
                    name = o.get("name", "?")[:28]
                    title = o.get("title", "")[:18]
                    self.set_font("Helvetica", "", 7.5)
                    self.set_text_color(*_MID)
                self.cell(5, 4, ">", ln=False)
                self.cell(0, 4, self._ascii(f"{name}  -  {title}"), ln=True)
        else:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*_MID)
            self.cell(col_w, 5, "No skip-trace data (POST /deals/{id}/skiptrace)", ln=True)
        left_end_y = self.get_y()

        # RIGHT — Assembled site
        self.set_xy(self.l_margin + col_w + 6, start_y)
        self._section_title("Site Assembly")
        if assembly and (assembly.get("parcel_count") or 0) > 1:
            self._kv("Parcels", str(assembly["parcel_count"]))
            self._kv("Combined value", _fmt_usd(assembly.get("total_land_value")))
            self._kv("Combined lot", _fmt_sqft(assembly.get("total_lot_size_sqft")))
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(*_GREEN)
            self.set_x(self.l_margin + col_w + 6)
            self.cell(col_w, 4, "Same-owner contiguous parcels detected", ln=True)  # noqa
        else:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*_MID)
            self.set_x(self.l_margin + col_w + 6)
            self.cell(col_w, 5, "No assembly - standalone parcel", ln=True)

        self.set_y(max(left_end_y, self.get_y()) + 3)

    def add_comps(self, comps: list[dict]):
        self._section_title("Comparable Sales  (1-mile radius, similar zoning, last 3 years)")
        if not comps:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*_MID)
            self.cell(0, 5, "No comparable sales found in the dataset.", ln=True)
            return

        col_widths = [62, 22, 20, 20, 22, 36]
        headers    = ["Address", "Zoning", "Sqft", "Sold", "Price", "$/sqft"]

        # Header row
        self.set_font("Helvetica", "B", 7)
        self.set_fill_color(*_DARK)
        self.set_text_color(*_WHITE)
        for w, h in zip(col_widths, headers):
            self.cell(w, 5, h, border=0, fill=True, ln=False)
        self.ln()

        # Data rows
        for i, c in enumerate(comps[:6]):
            self.set_fill_color(*(248, 250, 252) if i % 2 == 0 else _WHITE)
            self.set_text_color(*_DARK)
            self.set_font("Helvetica", "", 7)
            sqft = c.get("lot_size_sqft") or 0
            price = c.get("last_sale_price") or 0
            ppsf = (price / sqft) if sqft > 0 else None
            vals = [
                (c.get("address") or "—")[:32],
                c.get("zoning_code") or "—",
                _fmt_sqft(sqft),
                str(c.get("last_sale_date") or "—"),
                _fmt_usd(price),
                f"${ppsf:,.0f}/sf" if ppsf else "—",
            ]
            for w, v in zip(col_widths, vals):
                self.cell(w, 4.5, v, border=0, fill=True, ln=False)
            self.ln()
        self.ln(2)

    def add_footer_note(self):
        self.set_y(-14)
        self.set_font("Helvetica", "I", 6.5)
        self.set_text_color(*_MID)
        today = date.today().strftime("%B %d, %Y")
        self.cell(
            0, 4,
            f"Generated by DealScout {MODEL_VERSION} on {today}  -  "
            f"For internal use only - Prosper Group Miami",
            align=Align.C,
            ln=True,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def build_deal_memo(
    parcel: dict,
    score: dict,
    owner: Optional[dict] = None,
    assembly: Optional[dict] = None,
    comps: Optional[list[dict]] = None,
    mapbox_token: str = "",
) -> bytes:
    """
    Build a Deal Memo PDF and return the raw bytes.

    parcel  — dict from Parcel model
    score   — dict with 'tier', 'total', 'scores' keys
    owner   — OwnerProfile dict (or None)
    assembly — AssembledSite dict (or None)
    comps   — list of comparable Parcel dicts (or None)
    mapbox_token — Mapbox public token for aerial imagery
    """
    lon = parcel.get("lng") or parcel.get("lon") or 0.0
    lat = parcel.get("lat") or 0.0

    aerial_bytes = await _fetch_aerial_image(
        lon=float(lon), lat=float(lat),
        mapbox_token=mapbox_token,
    )

    pdf = _DealMemoPDF()

    pdf.add_header(
        tier=score.get("tier", "?"),
        total_score=score.get("total", 0),
        address=parcel.get("address", "Unknown address"),
        county=parcel.get("county", ""),
    )
    pdf.add_aerial(aerial_bytes)
    pdf.add_property_and_score(parcel, score)
    pdf.add_owner_and_assembly(owner, assembly)
    pdf.add_comps(comps or [])
    pdf.add_footer_note()

    return bytes(pdf.output())
