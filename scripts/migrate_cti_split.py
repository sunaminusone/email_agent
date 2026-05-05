"""CTI split migration: data move (pairs with sql/migrations/007).

Three things this script does, in one transaction:

  1. Move CAR-T attributes JSONB keys + parent 4 columns into cart_product_catalog.
  2. Move mRNA-LNP attributes JSONB keys + parent 4 columns into lnp_product_catalog.
     Web metafield names are normalized:
       applicationHanding → application_handling   (web typo fixed)
       dataSheet          → data_sheet_url
       cellTypeTested     → cell_type_tested
  3. Strip antibody_product_catalog.description_html → description (plaintext,
     HTML entities unescaped). Also fix HTML entities in storage (the only
     existing column with `&deg;` contamination — 69/3534 rows).

Idempotent: INSERT … ON CONFLICT DO UPDATE on the children, plain UPDATE on
antibody. Re-running is a no-op once parent attributes are purged.

DDL must already be applied (007 creates the child tables and antibody.description).
Cleanup of the parent's now-redundant columns is deferred to 008.
"""
from __future__ import annotations

import html as html_module
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path("/Users/promab/anaconda_projects/email_agent")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
import psycopg

load_dotenv(PROJECT_ROOT / ".env")
DATABASE_URL = os.environ["DATABASE_URL"]


CART_ATTR_KEYS = (
    "construct",
    "costimulatory_domain",
    "group_name",
    "group_type",
    "group_subtype",
    "group_summary",
    "cell_number",
    "marker",
    "unit",
)

# Web metafield key → child table column. The ones with renames are the
# typo'd applicationHanding and the camelCase metafields normalized to snake_case.
LNP_ATTR_KEY_TO_COLUMN = {
    "type": "type",
    "application": "application",
    "applicationHanding": "application_handling",
    "cellTypeTested": "cell_type_tested",
    "dataSheet": "data_sheet_url",
}


_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_PEND_RE = re.compile(r"</p>", re.IGNORECASE)


def html_to_text(s: str | None) -> str | None:
    """Strip HTML tags and unescape entities, preserving paragraph breaks."""
    if not s or not s.strip():
        return None
    s = _BR_RE.sub("\n", s)
    s = _PEND_RE.sub("\n", s)
    s = _TAG_RE.sub("", s)
    s = html_module.unescape(s)
    lines = [line.strip() for line in s.split("\n")]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned or None


def unescape_entities(s: str | None) -> str | None:
    if not s:
        return s
    return html_module.unescape(s)


def main() -> None:
    apply = "--apply" in sys.argv

    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        with conn.cursor() as cur:
            # ----------------------------------------------------------------
            # 1. CAR-T → cart_product_catalog
            # ----------------------------------------------------------------
            cur.execute(
                """
                SELECT id, formulation, shipping, storage, description, attributes
                FROM product_catalog
                WHERE business_line = 'CAR-T/CAR-NK'
                ORDER BY catalog_no
                """
            )
            cart_rows = cur.fetchall()
            print(f"[info] CAR-T rows to migrate: {len(cart_rows)}")

            for pid, formulation, shipping, storage, description, attrs in cart_rows:
                attrs = attrs or {}
                cur.execute(
                    """
                    INSERT INTO cart_product_catalog (
                        product_id, construct, costimulatory_domain,
                        group_name, group_type, group_subtype, group_summary,
                        cell_number, marker, unit,
                        formulation, shipping, storage, description
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    ON CONFLICT (product_id) DO UPDATE SET
                        construct            = EXCLUDED.construct,
                        costimulatory_domain = EXCLUDED.costimulatory_domain,
                        group_name           = EXCLUDED.group_name,
                        group_type           = EXCLUDED.group_type,
                        group_subtype        = EXCLUDED.group_subtype,
                        group_summary        = EXCLUDED.group_summary,
                        cell_number          = EXCLUDED.cell_number,
                        marker               = EXCLUDED.marker,
                        unit                 = EXCLUDED.unit,
                        formulation          = EXCLUDED.formulation,
                        shipping             = EXCLUDED.shipping,
                        storage              = EXCLUDED.storage,
                        description          = EXCLUDED.description
                    """,
                    (
                        pid,
                        attrs.get("construct"),
                        attrs.get("costimulatory_domain"),
                        attrs.get("group_name"),
                        attrs.get("group_type"),
                        attrs.get("group_subtype"),
                        attrs.get("group_summary"),
                        attrs.get("cell_number"),
                        attrs.get("marker"),
                        attrs.get("unit"),
                        formulation,
                        shipping,
                        storage,
                        description,
                    ),
                )
            print(f"[ok] cart_product_catalog upserted: {len(cart_rows)}")

            # ----------------------------------------------------------------
            # 2. mRNA-LNP → lnp_product_catalog
            # ----------------------------------------------------------------
            cur.execute(
                """
                SELECT id, formulation, shipping, storage, description, attributes
                FROM product_catalog
                WHERE business_line = 'mRNA-LNP'
                ORDER BY catalog_no
                """
            )
            lnp_rows = cur.fetchall()
            print(f"[info] mRNA-LNP rows to migrate: {len(lnp_rows)}")

            for pid, formulation, shipping, storage, description, attrs in lnp_rows:
                attrs = attrs or {}
                cur.execute(
                    """
                    INSERT INTO lnp_product_catalog (
                        product_id, type, application, application_handling,
                        cell_type_tested, data_sheet_url,
                        formulation, shipping, storage, description
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (product_id) DO UPDATE SET
                        type                 = EXCLUDED.type,
                        application          = EXCLUDED.application,
                        application_handling = EXCLUDED.application_handling,
                        cell_type_tested     = EXCLUDED.cell_type_tested,
                        data_sheet_url       = EXCLUDED.data_sheet_url,
                        formulation          = EXCLUDED.formulation,
                        shipping             = EXCLUDED.shipping,
                        storage              = EXCLUDED.storage,
                        description          = EXCLUDED.description
                    """,
                    (
                        pid,
                        attrs.get("type"),
                        attrs.get("application"),
                        attrs.get("applicationHanding"),
                        attrs.get("cellTypeTested"),
                        attrs.get("dataSheet"),
                        formulation,
                        shipping,
                        storage,
                        description,
                    ),
                )
            print(f"[ok] lnp_product_catalog upserted: {len(lnp_rows)}")

            # ----------------------------------------------------------------
            # 3. antibody: description_html → description (plaintext) + storage
            #    HTML entity unescape
            # ----------------------------------------------------------------
            cur.execute(
                """
                SELECT product_id, description_html, storage
                FROM antibody_product_catalog
                """
            )
            ab_rows = cur.fetchall()
            print(f"[info] antibody rows to process: {len(ab_rows)}")

            n_desc = 0
            n_storage_fix = 0
            params = []
            for pid, desc_html, storage in ab_rows:
                desc_text = html_to_text(desc_html)
                storage_clean = unescape_entities(storage) if storage and "&" in storage else storage
                if storage_clean != storage:
                    n_storage_fix += 1
                if desc_text:
                    n_desc += 1
                params.append((desc_text, storage_clean, pid))
            cur.executemany(
                "UPDATE antibody_product_catalog SET description = %s, storage = %s WHERE product_id = %s",
                params,
            )
            print(f"[ok] antibody.description filled: {n_desc} / {len(ab_rows)}")
            print(f"[ok] antibody.storage HTML entities unescaped: {n_storage_fix}")

            # ----------------------------------------------------------------
            # 4. Purge migrated keys from product_catalog.attributes JSONB
            # ----------------------------------------------------------------
            cur.execute(
                "UPDATE product_catalog SET attributes = attributes - %s::text[] "
                "WHERE business_line = 'CAR-T/CAR-NK'",
                (list(CART_ATTR_KEYS),),
            )
            print(f"[ok] CAR-T attributes purged on {cur.rowcount} rows ({len(CART_ATTR_KEYS)} keys)")

            cur.execute(
                "UPDATE product_catalog SET attributes = attributes - %s::text[] "
                "WHERE business_line = 'mRNA-LNP'",
                (list(LNP_ATTR_KEY_TO_COLUMN),),
            )
            print(f"[ok] mRNA-LNP attributes purged on {cur.rowcount} rows ({len(LNP_ATTR_KEY_TO_COLUMN)} keys)")

            # ----------------------------------------------------------------
            # 5. Sanity / coverage report
            # ----------------------------------------------------------------
            cur.execute("SELECT COUNT(*) FROM cart_product_catalog")
            n_cart = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM lnp_product_catalog")
            n_lnp = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(description) FROM antibody_product_catalog"
            )
            n_ab_desc = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM antibody_product_catalog WHERE storage LIKE '%%&%%'"
            )
            n_storage_residual = cur.fetchone()[0]
            cur.execute(
                """
                SELECT business_line,
                       COUNT(*) AS rows,
                       SUM(CASE WHEN attributes ?| %s::text[] THEN 1 ELSE 0 END) AS with_cart_keys,
                       SUM(CASE WHEN attributes ?| %s::text[] THEN 1 ELSE 0 END) AS with_lnp_keys
                FROM product_catalog
                WHERE business_line IN ('CAR-T/CAR-NK', 'mRNA-LNP')
                GROUP BY business_line
                """,
                (list(CART_ATTR_KEYS), list(LNP_ATTR_KEY_TO_COLUMN)),
            )
            residual = cur.fetchall()

            print()
            print(f"[verify] cart_product_catalog rows : {n_cart}  (expect 138)")
            print(f"[verify] lnp_product_catalog rows  : {n_lnp}   (expect 112)")
            print(f"[verify] antibody.description filled: {n_ab_desc}  (expect ~3452)")
            print(f"[verify] antibody.storage residual & : {n_storage_residual}  (expect 0)")
            print(f"[verify] parent attributes residue:")
            for bl, rows, cart_k, lnp_k in residual:
                print(f"   {bl:14s} rows={rows} with_cart_keys={cart_k} with_lnp_keys={lnp_k}")

            if not apply:
                conn.rollback()
                print("\n[DRY RUN] rolled back. Re-run with --apply to commit.")
            else:
                conn.commit()
                print("\n[COMMITTED]")


if __name__ == "__main__":
    main()
