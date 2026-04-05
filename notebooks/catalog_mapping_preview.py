import re
import uuid
from pathlib import Path

import pandas as pd


FILE_PATH = Path("/Users/promab/anaconda_projects/email_agent/data/processed/rag_files/CAR_T_products.xlsx")
SHEET_NAME = "Sheet1"
SOURCE_NAME = FILE_PATH.name
BUSINESS_LINE = "car_t"


def norm(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def normalize_title(text):
    normalized = norm(text)
    if not normalized:
        return None
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def extract_lead_time_days(value):
    text = norm(value)
    if not text:
        return None
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else None


def build_title(row):
    explicit_name = norm(row.get("name"))
    if explicit_name:
        return explicit_name

    parts = [
        norm(row.get("group_name")),
        norm(row.get("target_antigen")),
        norm(row.get("costimulatory_domain")),
        norm(row.get("catalog_no")),
    ]
    return " ".join(part for part in parts if part)


def build_description(row):
    summary = norm(row.get("group_summary"))
    if summary:
        return summary

    parts = [
        f"Target antigen: {norm(row.get('target_antigen'))}" if norm(row.get("target_antigen")) else None,
        f"Costimulatory domain: {norm(row.get('costimulatory_domain'))}" if norm(row.get("costimulatory_domain")) else None,
        f"Construct: {norm(row.get('construct'))}" if norm(row.get("construct")) else None,
        f"Cell number: {norm(row.get('cell_number'))}" if norm(row.get("cell_number")) else None,
        f"Marker: {norm(row.get('marker'))}" if norm(row.get("marker")) else None,
        f"Total time: {norm(row.get('total_time'))}" if norm(row.get("total_time")) else None,
    ]
    return " | ".join(part for part in parts if part) or None


def build_keywords(row):
    values = [
        norm(row.get("catalog_no")),
        norm(row.get("name")),
        norm(row.get("target_antigen")),
        norm(row.get("costimulatory_domain")),
        norm(row.get("construct")),
        norm(row.get("marker")),
        norm(row.get("group_name")),
        norm(row.get("group_type")),
        norm(row.get("group_subtype")),
        norm(row.get("unit")),
        norm(row.get("cell_number")),
    ]
    deduped = []
    seen = set()
    for value in values:
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(value)
    return deduped


def build_search_text(title, description, keywords, row):
    parts = [
        norm(row.get("catalog_no")),
        title,
        description,
        " ".join(keywords) if keywords else None,
        norm(row.get("group_name")),
        norm(row.get("group_type")),
        norm(row.get("group_subtype")),
        norm(row.get("target_antigen")),
        norm(row.get("construct")),
    ]
    return " | ".join(part for part in parts if part)


raw_df = pd.read_excel(FILE_PATH, sheet_name=SHEET_NAME)

records = []
for idx, row in raw_df.iterrows():
    title = build_title(row)
    description = build_description(row)
    keywords = build_keywords(row)

    records.append(
        {
            "id": str(uuid.uuid4()),
            "source_id": None,
            "source_type": "excel",
            "source_name": SOURCE_NAME,
            "source_sheet": SHEET_NAME,
            "source_row_number": idx + 2,
            "business_line": BUSINESS_LINE,
            "record_type": norm(row.get("group_type")) or "product",
            "product_family": norm(row.get("group_name")),
            "catalog_no": norm(row.get("catalog_no")),
            "title": title,
            "normalized_title": normalize_title(title),
            "description": description,
            "aliases": [],
            "keywords": keywords,
            "applications": [],
            "species_reactivity": [],
            "target": norm(row.get("target_antigen")),
            "gene_id": None,
            "gene_accession": None,
            "swissprot": None,
            "antibody_type": None,
            "clone_name": None,
            "isotype_or_class": None,
            "format_size": norm(row.get("unit")),
            "unit_price": float(row["price_usd"]) if pd.notna(row.get("price_usd")) else None,
            "currency": "USD",
            "availability_status": "catalog_available",
            "lead_time_days": extract_lead_time_days(row.get("total_time")),
            "name": norm(row.get("name")),
            "target_antigen": norm(row.get("target_antigen")),
            "costimulatory_domain": norm(row.get("costimulatory_domain")),
            "construct": norm(row.get("construct")),
            "total_time": norm(row.get("total_time")),
            "unit": norm(row.get("unit")),
            "cell_number": norm(row.get("cell_number")),
            "marker": norm(row.get("marker")),
            "group_name": norm(row.get("group_name")),
            "group_type": norm(row.get("group_type")),
            "group_subtype": norm(row.get("group_subtype")),
            "group_summary": norm(row.get("group_summary")),
            "raw_metadata": {
                column: (None if pd.isna(value) else value)
                for column, value in row.to_dict().items()
            },
            "search_text": build_search_text(title, description, keywords, row),
            "embedding": None,
            "is_active": True,
        }
    )

catalog_df = pd.DataFrame(records)

preview_columns = [
    "catalog_no",
    "name",
    "title",
    "record_type",
    "product_family",
    "target_antigen",
    "costimulatory_domain",
    "construct",
    "unit_price",
    "currency",
    "lead_time_days",
    "keywords",
    "description",
    "search_text",
]

compare_df = pd.DataFrame(
    {
        "catalog_no_raw": raw_df["catalog_no"],
        "name_raw": raw_df["name"],
        "group_name_raw": raw_df["group_name"],
        "group_type_raw": raw_df["group_type"],
        "target_antigen_raw": raw_df["target_antigen"],
        "costimulatory_domain_raw": raw_df["costimulatory_domain"],
        "construct_raw": raw_df["construct"],
        "price_usd_raw": raw_df["price_usd"],
        "title_new": catalog_df["title"],
        "record_type_new": catalog_df["record_type"],
        "product_family_new": catalog_df["product_family"],
        "unit_price_new": catalog_df["unit_price"],
        "keywords_new": catalog_df["keywords"],
    }
)

print("raw_df shape:", raw_df.shape)
print("catalog_df shape:", catalog_df.shape)

raw_df.head()
catalog_df[preview_columns].head(10)
compare_df.head(10)
