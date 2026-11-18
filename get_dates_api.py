"""
API-based recycling collection finder for Waipa District Council.

Talks directly to the council's IntraMaps backend (the same one the
"Recycling Day Finder" map tool uses) instead of driving a browser.
No Chromium/Playwright dependency, much faster, and returns clean
structured data instead of scraped page text.

See get_dates_working.py for the original Playwright-based approach,
kept around as a fallback in case the council ever changes this API.
"""

import argparse
import re
from datetime import datetime
from typing import Dict, List, Optional

import requests

BASE = "https://waipadc.spatial.t1cloud.com/spatial/IntraMaps/ApplicationEngine"
CONFIG_ID = "6aa41407-1db8-44e1-8487-0b9a08965283"
PROJECT_ID = "b5bc138e-edce-4b01-b159-ec44539ab455"
MODULE_ID = "5373c4e1-c975-4c8f-b51a-0ac976f5313c"
SELECTION_LAYER = "e7163a17-2f10-42b1-8dbf-8c53adf089a8"
SEARCH_FORM_ID = "e6677a33-9d47-407a-b199-5c7967a4be07"

COMMON_HEADERS = {
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://waipadc.spatial.t1cloud.com",
    "Referer": (
        f"{BASE}/frontend/mapbuilder/default.htm?configId={CONFIG_ID}"
    ),
}

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _start_session() -> str:
    """Mint a fresh IntraMaps session. The session id comes back as a
    response header (x-intramaps-session), not in the JSON body."""
    resp = requests.post(
        f"{BASE}/Projects/",
        params={
            "configId": CONFIG_ID,
            "appType": "MapBuilder",
            "project": PROJECT_ID,
            "datasetCode": "",
            "includeDisabledModules": "true",
        },
        headers=COMMON_HEADERS,
    )
    resp.raise_for_status()
    session = resp.headers.get("x-intramaps-session")
    if not session:
        raise RuntimeError("Council API did not return an IntraMaps session header")
    return session


def _load_module(session: str) -> None:
    """Load the Recycling Day Finder module into the session, which
    registers the selection layer used by the search/refine calls."""
    resp = requests.post(
        f"{BASE}/Modules/",
        params={"IntraMapsSession": session},
        headers=COMMON_HEADERS,
        json={"module": MODULE_ID},
    )
    resp.raise_for_status()


def search_address(session: str, address: str) -> List[Dict]:
    """Search for an address, returning a list of candidate matches,
    each with a mapKey/dbKey and a human-readable displayValue."""
    resp = requests.post(
        f"{BASE}/Search/",
        params={
            "infoPanelWidth": 350,
            "mode": "Refresh",
            "form": SEARCH_FORM_ID,
            "resubmit": "false",
            "selectionLayersFilter": SELECTION_LAYER,
            "IntraMapsSession": session,
        },
        headers=COMMON_HEADERS,
        json={"fields": [address]},
    )
    resp.raise_for_status()
    return resp.json().get("fullText") or []


def get_property_info(session: str, map_key: str, db_key: str) -> Dict:
    """Fetch the recycling info panel for a specific property."""
    resp = requests.post(
        f"{BASE}/Search/Refine/Set",
        params={"IntraMapsSession": session},
        headers=COMMON_HEADERS,
        json={
            "selectionLayer": SELECTION_LAYER,
            "mapKey": map_key,
            "infoPanelWidth": 350,
            "mode": "Refresh",
            "dbKey": db_key,
            "zoomType": "current",
        },
    )
    resp.raise_for_status()
    return resp.json()


def _get_field(fields: List[Dict], caption: str) -> Optional[str]:
    for field in fields:
        if field.get("caption") == caption:
            return field.get("value", {}).get("value")
    return None


def _parse_next_date(text: Optional[str]) -> Optional[str]:
    """Pull the first dd-Mon-yyyy date out of a sentence like
    'Will be collected on 17-Nov-2026, and then ...' and return it
    as an ISO date string."""
    if not text:
        return None
    match = re.search(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", text)
    if not match:
        return None
    day, mon, year = match.groups()
    month = MONTHS.get(mon)
    if not month:
        return None
    return datetime(int(year), month, int(day)).date().isoformat()


def get_recycling_dates(address: str, manual_select: bool = False) -> Optional[Dict]:
    """Look up recycling collection info for an address.

    Returns a dict with collection_day, mixed_recycling/glass_recycling
    (both the raw description text and a parsed next-date), route, and
    the matched property's display address - or None if nothing matched.
    """
    session = _start_session()
    _load_module(session)

    matches = search_address(session, address)
    if not matches:
        print(f"[ERROR] No property found matching '{address}'")
        return None

    chosen = matches[0]
    if len(matches) > 1:
        print(f"\n[INFO] Found {len(matches)} matching address(es):\n")
        for i, m in enumerate(matches, 1):
            print(f"  [{i}] {m['displayValue']}")
        if manual_select:
            while True:
                try:
                    choice = int(input(f"\nSelect address (1-{len(matches)}), or 0 for first: "))
                except ValueError:
                    print("Please enter a valid number")
                    continue
                if choice == 0:
                    break
                if 1 <= choice <= len(matches):
                    chosen = matches[choice - 1]
                    break
                print(f"Please enter a number between 0 and {len(matches)}")
        print(f"\n[INFO] Using: {chosen['displayValue']}")

    info = get_property_info(session, chosen["mapKey"], chosen["dbKey"])
    fields = info["infoPanels"]["info1"]["feature"]["fields"]

    mixed_text = _get_field(
        fields, "Mixed Recycling (YELLOW bin - Plastic 1 2 5, Paper, Cardboard, Cans):"
    )
    glass_text = _get_field(fields, "Glass Recycling (BLUE bin):")

    return {
        "input_address": address,
        "matched_address": chosen["displayValue"],
        "address": _get_field(fields, "Property Address"),
        "collection_day": _get_field(fields, "Your Collection Day is:"),
        "mixed_recycling": mixed_text,
        "mixed_recycling_next_date": _parse_next_date(mixed_text),
        "glass_recycling": glass_text,
        "glass_recycling_next_date": _parse_next_date(glass_text),
        "route": _get_field(fields, "Route"),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Waipa Recycling Collection Dates Finder (direct API version)"
    )
    parser.add_argument(
        "address",
        nargs="?",
        default="YOUR ADDRESS HERE",
        help="The address to look up (replace the default with your own)",
    )
    parser.add_argument(
        "--manual-select",
        action="store_true",
        help="If multiple addresses match, prompt to choose instead of using the first",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Waipa Recycling Collection Dates Finder (API)")
    print("=" * 70)
    print(f"\nLooking up: {args.address}\n")

    result = get_recycling_dates(args.address, manual_select=args.manual_select)

    if result:
        print("\n" + "=" * 70)
        print("COLLECTION INFORMATION")
        print("=" * 70)
        print(f"\nSearched Address: {result['input_address']}")
        print(f"Matched Address:  {result['matched_address']}")
        print(f"\nYour Collection Day is: {result['collection_day']}")

        if result["mixed_recycling"]:
            print(f"\nMixed Recycling (YELLOW bin):")
            print(f"  {result['mixed_recycling']}")

        if result["glass_recycling"]:
            print(f"\nGlass Recycling (BLUE bin):")
            print(f"  {result['glass_recycling']}")

        if result["route"]:
            print(f"\nRoute: {result['route']}")

        print("\n" + "=" * 70)
    else:
        print("[ERROR] Could not retrieve collection information")

    return result


if __name__ == "__main__":
    main()
