#!/usr/bin/env python3
"""Test: compare list fetch vs individual fetch for tags."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()


def get_access_token():
    from core.zoho import get_access_token as zoho_get_access_token
    return zoho_get_access_token()


access_token = get_access_token()
org_id = os.getenv('ZOHO_ORG_ID')

# Fetch list (page 1)
print("=== FETCH VIA LIST ===")
api_response = requests.get(
    "https://www.zohoapis.com/books/v3/salesorders",
    headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
    params={"organization_id": org_id, "page": 1, "per_page": 5}
)

data = api_response.json()
salesorders = data.get('salesorders', [])

if salesorders:
    first_so = salesorders[0]
    so_id = first_so.get('salesorder_id')
    line_items = first_so.get('line_items', [])

    print(f"First contract from list: {so_id}")
    print(f"Line items: {len(line_items)}")
    if line_items:
        print(f"First line item tags: {line_items[0].get('tags', [])}")

    # Now fetch same contract individually
    print(f"\n=== FETCH INDIVIDUALLY ===")
    api_response = requests.get(
        f"https://www.zohoapis.com/books/v3/salesorders/{so_id}",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        params={"organization_id": org_id}
    )

    data = api_response.json()
    if data.get('code') == 0:
        so = data.get('salesorder', {})
        line_items = so.get('line_items', [])

        print(f"Same contract via individual fetch: {so_id}")
        print(f"Line items: {len(line_items)}")
        if line_items:
            print(f"First line item tags: {line_items[0].get('tags', [])}")