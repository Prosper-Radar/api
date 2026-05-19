"""
Seed 60 realistic Miami-Dade parcels directly into the Python API schema.
Uses real Miami addresses, folio formats, zoning codes, and scoring engine.

Run:
  python scripts/seed_miami_parcels.py
"""
import asyncio
import json
import os
import random
import uuid
from datetime import date

# Use psycopg2 (sync) to avoid asyncpg cast issues
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.environ.get("DATABASE_URL", "")

# ── Real Miami-Dade neighbourhoods + realistic addresses ─────────────────────

PARCELS_RAW = [
    # (folio, address, lat, lng, zoning, acreage, land_val, bldg_val, owner, sale_price, sale_year)
    # Brickell / Downtown
    ("01-0203-060-1010", "80 SW 8th St",          25.7640, -80.1960, "T6-48A-O",  0.45,  2_800_000, 18_000_000, "BRICKELL CITY CENTRE LLC",       45_000_000, 2022),
    ("01-0203-080-1020", "501 Brickell Key Dr",    25.7631, -80.1879, "T6-36-O",   0.31,  1_900_000,  9_500_000, "MANDARIN ORIENTAL MIAMI",        32_000_000, 2021),
    ("01-0203-050-0030", "1395 Brickell Ave",      25.7609, -80.1932, "T6-48-O",   0.52,  3_200_000, 22_000_000, "CITIGROUP CENTER LLC",           55_000_000, 2023),
    ("01-4138-001-0010", "175 SW 7th St",          25.7651, -80.1955, "T6-24-O",   0.28,  1_400_000,  6_200_000, "BRICKELL PLAZA LLC",             18_500_000, 2022),
    ("01-0203-010-0040", "600 Brickell Ave",       25.7590, -80.1937, "T6-60-O",   0.61,  4_100_000, 28_000_000, "600 BRICKELL LLC",               72_000_000, 2019),
    # Wynwood / Edgewater
    ("01-3130-030-0010", "2750 NW 3rd Ave",        25.8010, -80.2050, "D3",        0.39,    780_000,  2_100_000, "WYNWOOD WALLS LLC",               7_200_000, 2023),
    ("01-3230-020-0020", "3841 NE 2nd Ave",        25.8155, -80.1985, "T5-O",      0.27,    520_000,  1_400_000, "NE 2ND AVE PARTNERS",             4_100_000, 2022),
    ("01-3120-040-0030", "2200 NW 2nd Ave",        25.7990, -80.2020, "T6-8-O",    0.33,    640_000,  1_800_000, "WYNWOOD REAL ESTATE FUND",        5_800_000, 2021),
    ("01-3228-040-0010", "3250 NE 1st Ave",        25.8070, -80.1940, "T5-R",      0.22,    410_000,    980_000, "3250 EDGEWATER LLC",              3_200_000, 2023),
    ("01-4119-003-0010", "2143 NW 5th Ave",        25.8024, -80.2040, "T5-O",      0.44,    870_000,  2_500_000, "ARTPLACE WYNWOOD INC",            8_500_000, 2022),
    # Little Havana / Allapattah
    ("01-4108-007-0050", "1500 SW 8th St",         25.7680, -80.2200, "T5-O",      0.31,    420_000,  1_100_000, "CALLE OCHO PROPERTIES LLC",       3_800_000, 2022),
    ("01-3415-010-0010", "1900 NW 20th St",        25.8010, -80.2310, "T5-O",      0.56,    690_000,  1_500_000, "ALLAPATTAH VENTURES",             5_100_000, 2021),
    ("01-4107-009-0020", "1250 SW 27th Ave",       25.7559, -80.2350, "T4-R",      0.24,    310_000,    750_000, "CORAL GABLES INVESTMENT GROUP",   2_400_000, 2022),
    ("01-4117-005-0030", "2701 W Flagler St",      25.7700, -80.2290, "T5-O",      0.36,    480_000,  1_200_000, "FLAGLER HOLDINGS LLC",            3_900_000, 2023),
    ("01-3420-015-0010", "1800 NW 36th St",        25.8130, -80.2400, "IU-1",      0.78,    960_000,  2_800_000, "ALLAPATTAH INDUSTRIAL LLC",       6_200_000, 2020),
    # Coconut Grove / Coral Gables border
    ("01-4120-008-0070", "2699 S Bayshore Dr",     25.7279, -80.2350, "T3-R",      0.41,  1_100_000,  3_200_000, "GROVE BAYFRONT LLC",             8_900_000, 2023),
    ("01-4130-010-0010", "3300 Mary St",           25.7270, -80.2430, "T4-O",      0.29,    590_000,  1_600_000, "GROVE VILLAGE PARTNERS",          4_500_000, 2022),
    ("03-4109-005-0020", "3690 Bird Rd",           25.7430, -80.2820, "T5-O",      0.35,    540_000,  1_450_000, "BIRD ROAD REALTY LLC",            3_800_000, 2021),
    ("03-4118-012-0010", "2020 SW 57th Ave",       25.7485, -80.2850, "T4-R",      0.26,    320_000,    870_000, "WESTCHESTER INVESTMENT GROUP",    2_600_000, 2022),
    # Little River / NE Miami
    ("01-3120-075-0010", "8000 NE 2nd Ave",        25.8510, -80.1910, "T5-O",      0.34,    430_000,  1_100_000, "LITTLE RIVER CREATIVE LLC",       3_500_000, 2023),
    ("01-3131-020-0030", "7900 NE 2nd Ave",        25.8499, -80.1912, "T5-R",      0.27,    360_000,    890_000, "UPPER EAST SIDE PARTNERS",        2_900_000, 2022),
    ("01-3127-005-0010", "7600 Biscayne Blvd",     25.8470, -80.1870, "T6-8-O",    0.42,    780_000,  2_100_000, "MODERA BISCAYNE LLC",             6_800_000, 2023),
    # Overtown / Park West
    ("01-0102-030-1020", "1201 NW 3rd Ave",        25.7790, -80.1990, "T6-24-O",   0.55,  1_200_000,  3_800_000, "OVERTOWN GATEWAY LLC",           11_000_000, 2022),
    ("01-0103-020-0010", "600 NW 7th Ave",         25.7820, -80.2080, "T6-12-O",   0.44,    890_000,  2_400_000, "PARK WEST DEVELOPMENT GROUP",     7_500_000, 2021),
    ("01-4122-001-0040", "350 NW 14th St",         25.7870, -80.1960, "T6-8-O",    0.37,    720_000,  1_900_000, "OVERTOWN REVITALIZATION CORP",    5_200_000, 2023),
    # Design District
    ("01-3226-035-0010", "140 NE 39th St",         25.8210, -80.1930, "T6-8-O",    0.32,  1_800_000,  5_200_000, "DESIGN DISTRICT ASSOCIATES",    18_000_000, 2022),
    ("01-3226-038-0020", "4150 NE 2nd Ave",        25.8230, -80.1935, "D3",        0.24,  1_400_000,  3_800_000, "DDM LLC",                        12_500_000, 2021),
    ("01-3226-031-0010", "3921 NE 1st Ct",         25.8199, -80.1940, "T5-O",      0.21,    980_000,  2_600_000, "MEZZ CAPITAL LLC",                8_200_000, 2023),
    # Miami Beach (Miami-Dade County)
    ("02-3231-010-0010", "1500 Ocean Dr",           25.7840, -80.1300, "CD-2",      0.28,  3_500_000, 12_000_000, "OCEAN DR HOTEL GROUP",           28_000_000, 2022),
    ("02-3231-012-0020", "700 Collins Ave",         25.7810, -80.1310, "CD-1",      0.20,  2_800_000,  8_500_000, "MIAMI BEACH HOSPITALITY",        18_500_000, 2021),
    ("02-4203-003-0010", "4041 Pine Tree Dr",       25.8040, -80.1430, "RS-3",      0.55,  2_200_000,  6_500_000, "PALM ISLAND HOLDINGS LLC",       14_000_000, 2023),
    ("02-3228-001-0030", "2020 N Bayshore Dr",      25.7990, -80.1530, "RM-50",     0.38,  1_600_000,  4_200_000, "BAYSHORE NORTH LLC",             10_500_000, 2022),
    # Doral / West Miami-Dade
    ("35-3018-001-0150", "9400 NW 97th Ave",        25.8180, -80.3580, "IU-2",      1.25,    980_000,  3_200_000, "DORAL INDUSTRIAL PARK LLC",       7_800_000, 2022),
    ("35-3022-002-0010", "8400 NW 53rd St",         25.8090, -80.3480, "IU-1",      0.98,    780_000,  2_600_000, "DORAL COMMERCE CENTER",           6_200_000, 2021),
    ("35-3015-003-0020", "10800 NW 33rd St",        25.8270, -80.3650, "GU",        0.72,    560_000,  1_800_000, "FLAGLER PARK LLC",                4_500_000, 2023),
    # Hialeah
    ("04-3123-010-0020", "1500 W 68th St",          25.8710, -80.3010, "C-1",       0.45,    380_000,  1_100_000, "HIALEAH RETAIL LLC",              2_800_000, 2022),
    ("04-3122-007-0030", "900 W 29th St",           25.8400, -80.2950, "M-1",       0.62,    490_000,  1_500_000, "HIALEAH INDUSTRIAL GROUP",        3_800_000, 2021),
    ("04-3129-005-0010", "2040 E 4th Ave",          25.8290, -80.2780, "C-2",       0.37,    340_000,    920_000, "HIALEAH COMMERCIAL PROP",         2_300_000, 2023),
    # Homestead / South Miami-Dade
    ("10-7935-001-0040", "401 N Krome Ave",         25.4820, -80.4820, "BU-2",      0.55,    220_000,    680_000, "HOMESTEAD MAIN ST LLC",           1_600_000, 2022),
    ("10-7935-010-0010", "1120 N Flagler Ave",      25.4840, -80.4790, "BU-1",      0.38,    180_000,    520_000, "SOUTH DADE REALTY INC",           1_100_000, 2021),
    # North Miami / Aventura
    ("06-3121-011-0010", "1980 NE 149th St",        25.9120, -80.1720, "T5-O",      0.31,    520_000,  1_400_000, "NORTH MIAMI PARTNERS LLC",        3_800_000, 2022),
    ("28-2235-001-0010", "19999 Biscayne Blvd",     25.9630, -80.1390, "B2",        0.44,  1_200_000,  3_800_000, "AVENTURA BLVD LLC",               9_500_000, 2023),
    ("28-2235-004-0020", "2999 Aventura Blvd",      25.9580, -80.1420, "B2",        0.36,    980_000,  2_800_000, "AV RETAIL GROUP",                 6_200_000, 2021),
    # Coral Gables
    ("03-4107-001-0010", "150 Alhambra Plaza",      25.7520, -80.2630, "SRM-1",     0.42,  1_400_000,  4_500_000, "CORAL GABLES CORP CENTER",       12_000_000, 2022),
    ("03-4107-005-0020", "396 Alhambra Cir",        25.7498, -80.2611, "SRM-1",     0.29,    980_000,  3_100_000, "ALHAMBRA OFFICES LLC",            7_500_000, 2023),
    ("03-4112-012-0010", "3950 Ponce de Leon Blvd", 25.7430, -80.2640, "T5-L",      0.35,    760_000,  2_300_000, "PONCE DE LEON HOLDINGS",          6_000_000, 2021),
    # Key Biscayne
    ("24-4235-023-0010", "320 Crandon Blvd",        25.6900, -80.1560, "BU-1A",     0.22,  1_800_000,  5_500_000, "CRANDON VILLAGE LLC",            13_000_000, 2022),
    ("24-4235-030-0020", "180 Ocean Dr",            25.6840, -80.1590, "BU-1A",     0.18,  1_600_000,  4_800_000, "KEY BISCAYNE REALTY",            11_000_000, 2023),
    # Opa-locka / NW Miami-Dade
    ("08-2117-001-0020", "780 Fisherman St",        25.9060, -80.2490, "I-1",       0.92,    420_000,  1_400_000, "OPA LOCKA INDUSTRIAL LLC",        3_500_000, 2022),
    ("08-2116-008-0010", "2100 NW 135th St",        25.8930, -80.2550, "I-1",       1.10,    510_000,  1_700_000, "NORTHWEST COMMERCE PARK",         4_100_000, 2021),
    # NW Airport / Springs
    ("30-2903-001-0010", "4800 NW 183rd St",        25.9420, -80.3210, "I-1",       1.35,    680_000,  2_200_000, "MIAMI SPRINGS LOGISTICS LLC",     5_800_000, 2022),
    # Virginia Gardens / Medley
    ("32-2913-001-0020", "7900 NW 29th St",         25.8210, -80.3380, "IU-2",      1.80,  1_200_000,  4_100_000, "MEDLEY BUSINESS PARK",            8_500_000, 2023),
    # Bal Harbour / Surfside
    ("12-2226-001-0010", "9700 Collins Ave",        25.9020, -80.1230, "B2",        0.33,  3_200_000, 11_000_000, "BAL HARBOUR SHOPS LLC",          28_000_000, 2022),
    # Kendale Lakes
    ("30-4036-012-0010", "11200 SW 137th Ave",      25.7020, -80.4250, "RS-2",      0.28,    290_000,    850_000, "KENDALE LAKES HOME INVEST",       2_100_000, 2021),
    # Palmetto Bay
    ("33-5026-010-0010", "17801 SW 87th Ave",       25.6250, -80.3510, "RS-2.5",    0.37,    380_000,  1_100_000, "PALMETTO BAY RESIDENTIAL",        2_800_000, 2022),
    # Pinecrest
    ("20-5010-015-0020", "7750 SW 100th St",        25.6680, -80.3180, "EU-1",      0.44,    520_000,  1_600_000, "PINECREST ESTATE LLC",            3_600_000, 2023),
    # South Beach / SoFi
    ("02-3235-027-0010", "1 Hotel South Beach",     25.7680, -80.1280, "CD-2",      0.62,  5_100_000, 22_000_000, "1 HOTEL SB LLC",                 48_000_000, 2021),
    # Liberty City
    ("01-3105-020-0010", "6500 NW 7th Ave",         25.8380, -80.2100, "T5-O",      0.48,    380_000,  1_050_000, "LIBERTY CITY VENTURES LLC",       2_900_000, 2022),
    # Sweetwater
    ("39-3906-001-0020", "1920 SW 104th Ave",       25.7620, -80.3630, "BU-2",      0.39,    310_000,    920_000, "SWEETWATER COMMERCIAL LLC",       2_400_000, 2021),
]

random.seed(42)


def _sale_date(year: int) -> date:
    return date(year, random.randint(1, 12), random.randint(1, 28))


def _score_breakdown(land_val: int, bldg_val: int, acreage: float, zoning: str, sale_price: int, sale_year: int) -> dict:
    """Generate a realistic score breakdown dict for the deal_scores breakdown column."""
    # Momentum: recent sales boost score
    years_ago = 2026 - sale_year
    momentum = max(20, 100 - years_ago * 15)

    # Location: based on land value per sqft (proxy for desirability)
    sqft = acreage * 43_560
    land_per_sqft = land_val / sqft if sqft > 0 else 0
    location = min(100, int(land_per_sqft * 2))

    # Value: land value as fraction of total (lower ratio = more upside)
    total = land_val + bldg_val
    land_ratio = land_val / total if total > 0 else 0.5
    value = int(70 + (0.6 - land_ratio) * 60)  # high land ratio = closer to land value
    value = max(10, min(100, value))

    # Liquidity: based on zoning (commercial/mixed-use > residential)
    zone_prefix = zoning.split("-")[0] if zoning else "RS"
    liq_map = {"T6": 95, "T5": 85, "D3": 80, "IU": 75, "CD": 90, "BU": 80,
               "B2": 82, "C": 75, "M": 70, "I": 70, "T4": 70, "RS": 55, "EU": 50}
    liquidity = liq_map.get(zone_prefix, 65)
    liquidity += random.randint(-5, 5)
    liquidity = max(10, min(100, liquidity))

    total_score = int((momentum * 0.25 + location * 0.30 + value * 0.25 + liquidity * 0.20))
    return {"momentum": momentum, "location": location, "value": value, "liquidity": liquidity}, total_score


def main():
    if not DB_URL:
        raise SystemExit("DATABASE_URL env var not set")

    conn = psycopg2.connect(DB_URL, options="-c statement_timeout=30000")
    cur = conn.cursor()

    inserted_parcels = 0
    inserted_scores = 0

    for row in PARCELS_RAW:
        folio, address, lat, lng, zoning, acreage, land_val, bldg_val, owner, sale_price, sale_year = row
        lot_sqft = round(acreage * 43_560, 1)
        breakdown, total_score = _score_breakdown(land_val, bldg_val, acreage, zoning, sale_price, sale_year)
        tier = "A" if total_score >= 80 else "B" if total_score >= 65 else "C"
        sale_dt = _sale_date(sale_year)

        # Check if folio exists
        cur.execute("SELECT id FROM parcels WHERE folio = %s", (folio,))
        existing = cur.fetchone()

        if existing:
            parcel_uuid = str(existing[0])
            cur.execute("""
                UPDATE parcels SET
                    parcel_id      = %s, address       = %s, owner_name     = %s,
                    land_value     = %s, building_value = %s, total_value   = %s,
                    lot_size_sqft  = %s, zoning_code    = %s,
                    last_sale_date = %s, last_sale_price = %s
                WHERE folio = %s
            """, (folio, address, owner, land_val, bldg_val, land_val + bldg_val,
                  lot_sqft, zoning, sale_dt, sale_price, folio))
        else:
            parcel_uuid = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO parcels (id, folio, address_line, city, state, zip, county, lat, lng, acreage, zoning,
                                     parcel_id, address, owner_name, land_value, building_value, total_value,
                                     lot_size_sqft, zoning_code, last_sale_date, last_sale_price)
                VALUES (%s, %s, %s, 'Miami', 'FL', '33101', 'Miami-Dade', %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (parcel_uuid, folio, address, lat, lng, acreage, zoning,
                  folio, address, owner, land_val, bldg_val, land_val + bldg_val,
                  lot_sqft, zoning, sale_dt, sale_price))
            inserted_parcels += 1

        # Upsert deal_score using ON CONFLICT
        cur.execute("""
            INSERT INTO deal_scores (id, parcel_id, total_score, breakdown, model_version,
                                     waterfront_score, zoning_score, price_score, lot_size_score,
                                     population_score, traffic_score, recency_score, tier)
            VALUES (%s, %s, %s, %s, 'v1-realistic', %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (parcel_id) DO UPDATE SET
                total_score      = EXCLUDED.total_score,
                breakdown        = EXCLUDED.breakdown,
                model_version    = EXCLUDED.model_version,
                waterfront_score = EXCLUDED.waterfront_score,
                zoning_score     = EXCLUDED.zoning_score,
                price_score      = EXCLUDED.price_score,
                lot_size_score   = EXCLUDED.lot_size_score,
                population_score = EXCLUDED.population_score,
                traffic_score    = EXCLUDED.traffic_score,
                recency_score    = EXCLUDED.recency_score,
                tier             = EXCLUDED.tier,
                computed_at      = now()
        """, (
            str(uuid.uuid4()),
            parcel_uuid,
            total_score,
            json.dumps(breakdown),
            round(breakdown["location"] / 2, 1),
            round(breakdown["value"], 1),
            round(breakdown["value"], 1),
            round(breakdown["momentum"], 1),
            round(breakdown["location"], 1),
            round(breakdown["liquidity"], 1),
            50,
            tier,
        ))
        inserted_scores += 1

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM parcels")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM deal_scores")
    score_total = cur.fetchone()[0]
    cur.close()
    conn.close()

    print(f"Done — {inserted_parcels} new parcels, {inserted_scores} scores upserted")
    print(f"Total in DB: {total} parcels, {score_total} deal_scores")


main()
