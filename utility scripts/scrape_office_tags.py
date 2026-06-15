#!/usr/bin/env python3
"""
Scrape office reporting tag IDs from existing Zoho contracts.
Fetches contract list, then fetches each individually to get tags.
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()


def get_access_token():
    """Get Zoho access token."""
    from core.zoho import get_access_token as zoho_get_access_token
    return zoho_get_access_token()


def scrape_office_tags(max_contracts=500):
    """Fetch contracts individually and extract office tag mappings."""
    access_token = get_access_token()
    org_id = os.getenv('ZOHO_ORG_ID')

    office_map = {}
    salesorder_ids = []
    page = 1
    per_page = 50

    print(f"Step 1: Fetching up to {max_contracts} contract IDs...")
    print("=" * 70)

    # Step 1: Get list of salesorder IDs
    while len(salesorder_ids) < max_contracts:
        print(f"[Page {page}] Fetching contract IDs...", flush=True)

        api_response = requests.get(
            "https://www.zohoapis.com/books/v3/salesorders",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={
                "organization_id": org_id,
                "page": page,
                "per_page": per_page
            }
        )

        data = api_response.json()
        if data.get('code') != 0:
            print(f"Error: {data.get('message')}")
            break

        salesorders = data.get('salesorders', [])
        if not salesorders:
            print(f"No more contracts at page {page}")
            break

        for so in salesorders:
            if len(salesorder_ids) >= max_contracts:
                break
            salesorder_ids.append(so.get('salesorder_id'))

        print(f"[Page {page}] Got {len(salesorder_ids)} total IDs so far", flush=True)
        page += 1

    print(f"\nStep 2: Fetching {len(salesorder_ids)} contracts individually for tags...")
    print("=" * 70)

    # Step 2: Fetch each contract individually and extract tags
    for idx, so_id in enumerate(salesorder_ids):
        print(f"[{idx + 1}/{len(salesorder_ids)}] Fetching {so_id}...", flush=True)

        api_response = requests.get(
            f"https://www.zohoapis.com/books/v3/salesorders/{so_id}",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={"organization_id": org_id}
        )

        data = api_response.json()
        if data.get('code') != 0:
            print(f"  Error: {data.get('message')}", flush=True)
            continue

        so = data.get('salesorder', {})
        line_items = so.get('line_items', [])

        for line_item in line_items:
            tags = line_item.get('tags', [])
            for tag in tags:
                if tag.get('tag_name') == 'Office':
                    office_name = tag.get('tag_option_name')
                    tag_option_id = tag.get('tag_option_id')

                    if office_name and tag_option_id:
                        if office_name not in office_map:
                            office_map[office_name] = tag_option_id
                            print(f"  Found: {office_name:30} -> {tag_option_id}")
                    break  # Only one Office tag per line item

    print("=" * 70)
    print(f"Fetched {len(salesorder_ids)} contracts")
    print(f"Found {len(office_map)} unique offices\n")

    # Output as Python dict
    print("Add this to get_office_tag_option_id() in zoho.py:\n")
    print("office_map = {")
    for office_name in sorted(office_map.keys()):
        tag_id = office_map[office_name]
        print(f"    '{office_name}': '{tag_id}',")
    print("}")

    return office_map


if __name__ == '__main__':
    max_contracts = 500
    if len(sys.argv) > 1:
        try:
            max_contracts = int(sys.argv[1])
        except ValueError:
            print(f"Usage: {sys.argv[0]} [max_contracts]")
            sys.exit(1)

    scrape_office_tags(max_contracts)