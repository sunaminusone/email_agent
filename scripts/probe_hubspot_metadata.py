"""Probe HubSpot for form list and contact property schema.

Use this to identify the correct form GUIDs and contact property internal
names before running the main form inquiry export. Pipe output into a file
and share it to decide which forms to export and which properties to pull.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_hubspot_settings

import requests


def build_session() -> requests.Session:
    settings = get_hubspot_settings()
    if not settings.get("is_configured"):
        raise SystemExit("HUBSPOT_ACCESS_TOKEN not set in .env")
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {settings['access_token']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )
    session.base_url = settings["base_url"]  # type: ignore[attr-defined]
    return session


def paginate(session: requests.Session, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    next_after: str | None = None
    while True:
        query = dict(params or {})
        if next_after:
            query["after"] = next_after
        response = session.get(f"{session.base_url}{path}", params=query, timeout=30)  # type: ignore[attr-defined]
        response.raise_for_status()
        payload = response.json()
        results.extend(payload.get("results", []))
        next_after = (((payload.get("paging") or {}).get("next") or {}).get("after"))
        if not next_after:
            break
    return results


def list_forms(session: requests.Session) -> list[dict[str, Any]]:
    forms = paginate(session, "/marketing/v3/forms", params={"limit": 100})
    rows: list[dict[str, Any]] = []
    for form in forms:
        rows.append(
            {
                "id": form.get("id"),
                "name": form.get("name"),
                "formType": form.get("formType"),
                "archived": form.get("archived"),
                "createdAt": form.get("createdAt"),
                "updatedAt": form.get("updatedAt"),
            }
        )
    rows.sort(key=lambda item: (item.get("archived") or False, item.get("createdAt") or ""))
    return rows


def list_contact_properties(session: requests.Session) -> list[dict[str, Any]]:
    response = session.get(f"{session.base_url}/crm/v3/properties/contacts", timeout=30)  # type: ignore[attr-defined]
    response.raise_for_status()
    payload = response.json()
    rows: list[dict[str, Any]] = []
    for prop in payload.get("results", []):
        rows.append(
            {
                "name": prop.get("name"),
                "label": prop.get("label"),
                "type": prop.get("type"),
                "fieldType": prop.get("fieldType"),
                "groupName": prop.get("groupName"),
                "custom": not prop.get("hubspotDefined", False),
            }
        )
    rows.sort(key=lambda item: (not item["custom"], item["groupName"] or "", item["name"] or ""))
    return rows


def sample_form_submission(session: requests.Session, form_id: str) -> dict[str, Any]:
    response = session.get(
        f"{session.base_url}/form-integrations/v1/submissions/forms/{form_id}",  # type: ignore[attr-defined]
        params={"limit": 1},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results", [])
    return results[0] if results else {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-form-id",
        help="If provided, also fetch one sample submission from this form to preview field keys.",
    )
    parser.add_argument(
        "--out-dir",
        default="data/hubspot_probe",
        help="Where to write JSON dumps (forms.json, contact_properties.json, sample_submission.json).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session = build_session()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    forms = list_forms(session)
    (out_dir / "forms.json").write_text(json.dumps(forms, indent=2, ensure_ascii=False))
    print(f"[forms] total={len(forms)} -> {out_dir/'forms.json'}")
    print("\nActive forms (id | name | createdAt):")
    for form in forms:
        if form.get("archived"):
            continue
        print(f"  {form['id']}  {form['name']}  {form['createdAt']}")

    props = list_contact_properties(session)
    (out_dir / "contact_properties.json").write_text(json.dumps(props, indent=2, ensure_ascii=False))
    custom_props = [p for p in props if p["custom"]]
    print(f"\n[contact properties] total={len(props)} custom={len(custom_props)} -> {out_dir/'contact_properties.json'}")
    print("\nCustom contact properties (name | label | type):")
    for prop in custom_props:
        print(f"  {prop['name']}  |  {prop['label']}  |  {prop['type']}")

    if args.sample_form_id:
        sample = sample_form_submission(session, args.sample_form_id)
        (out_dir / "sample_submission.json").write_text(json.dumps(sample, indent=2, ensure_ascii=False))
        print(f"\n[sample submission] form_id={args.sample_form_id} -> {out_dir/'sample_submission.json'}")
        if sample:
            print("Submission field keys:")
            for value in sample.get("values", []):
                print(f"  name={value.get('name')!r}  objectTypeId={value.get('objectTypeId')}  value_preview={str(value.get('value', ''))[:80]!r}")


if __name__ == "__main__":
    main()
