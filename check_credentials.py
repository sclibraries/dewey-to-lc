#!/usr/bin/env python3
"""Quick credential check for WorldCat and loc.gov APIs.

Usage:
    python3 check_credentials.py

Reads WORLDCAT_CLIENT_ID and WORLDCAT_CLIENT_SECRET from .env or environment.
Makes one real API call each to verify connectivity and auth.
"""

import os
import sys
from pathlib import Path

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def check_worldcat(client_id: str, client_secret: str) -> bool:
    print("\n── WorldCat Metadata API ──────────────────────────")
    try:
        from bookops_worldcat import WorldcatAccessToken, MetadataSession

        print("  Requesting access token...", end=" ", flush=True)
        token = WorldcatAccessToken(
            key=client_id,
            secret=client_secret,
            scopes="WorldCatMetadataAPI",
        )
        print("✓")

        print("  Fetching classification for a known record (OCLC# 41266045)...", end=" ", flush=True)
        with MetadataSession(authorization=token) as session:
            response = session.bib_get_classification(oclcNumber="41266045")

        if response.status_code == 200:
            data = response.json()
            lc_popular = data.get("lc", {}).get("mostPopular", [])
            dewey_popular = data.get("dewey", {}).get("mostPopular", [])
            if lc_popular:
                print("✓")
                print(f"  LC classification returned : {lc_popular[0]}")
                if dewey_popular:
                    print(f"  Dewey classification       : {dewey_popular[0]}")
                print("  WorldCat credentials: ✓ WORKING")
                return True
            else:
                print("✓ (connected, but no LC classification for test record)")
                print("  WorldCat credentials: ✓ WORKING (auth OK)")
                return True
        else:
            print(f"✗ (HTTP {response.status_code})")
            print("  WorldCat credentials: ✗ FAILED")
            return False

    except Exception as exc:
        print(f"✗\n  Error: {exc}")
        print("  WorldCat credentials: ✗ FAILED")
        return False


def check_loc_gov() -> bool:
    print("\n── loc.gov Public API (no credentials required) ──")
    try:
        import requests
        print("  Searching for a known ISBN (9780134444321)...", end=" ", flush=True)
        response = requests.get(
            "https://www.loc.gov/books/",
            params={"q": "9780134444321", "fo": "json", "at": "results"},
            timeout=10,
            headers={"User-Agent": "dewey-to-lc/check-credentials"},
        )
        if response.status_code == 200:
            data = response.json()
            count = len(data.get("results", []))
            print(f"✓ ({count} result(s) returned)")
            print("  loc.gov API: ✓ REACHABLE")
            return True
        else:
            print(f"✗ (HTTP {response.status_code})")
            print("  loc.gov API: ✗ UNREACHABLE")
            return False
    except Exception as exc:
        print(f"✗\n  Error: {exc}")
        print("  loc.gov API: ✗ UNREACHABLE")
        return False


def main():
    print("dewey-to-lc — Credential Check")
    print("=" * 50)

    client_id = os.environ.get("WORLDCAT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("WORLDCAT_CLIENT_SECRET", "").strip()

    worldcat_ok = False
    if client_id and client_secret:
        worldcat_ok = check_worldcat(client_id, client_secret)
    else:
        print("\n── WorldCat Metadata API ──────────────────────────")
        print("  ⚠  WORLDCAT_CLIENT_ID / WORLDCAT_CLIENT_SECRET not set.")
        print("  Set them in .env or as environment variables.")

    loc_ok = check_loc_gov()

    print("\n" + "=" * 50)
    print("Summary:")
    print(f"  WorldCat Metadata API : {'✓ OK' if worldcat_ok else '✗ FAILED (or not configured)'}")
    print(f"  loc.gov API           : {'✓ OK' if loc_ok else '✗ FAILED'}")

    if not worldcat_ok:
        print("\n  Without WorldCat, conversion will fall back to loc.gov only.")
        print("  Some records may not get an LC match and will need manual review.")

    sys.exit(0 if loc_ok else 1)


if __name__ == "__main__":
    main()
