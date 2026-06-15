#!/usr/bin/env python3
"""Test: fetch a single contract to see if tags are in the API response."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()


def get_access_token():
    from core.zoho import get_access_token as zoho_get_access_token
    return zoho_get_access_token()


# Pick a recent contract - change this to one you know has tags
salesorder_id = input("Enter a salesorder_id to test (one you know has tags): ")

access_token = get_access_token()
org_id = os.getenv('ZOHO_ORG_ID')

print(f"\nFetching {salesorder_id}...\n")

api_response = requests.get(
    f"https://www.zohoapis.com/books/v3/salesorders/{salesorder_id}",
    headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
    params={"organization_id": org_id}
)

data = api_response.json()

if data.get('code') == 0:
    so = data.get('salesorder', {})
    line_items = so.get('line_items', [])
    print(f"Line items: {len(line_items)}\n")

    for idx, item in enumerate(line_items):
        print(f"Line Item {idx}:")
        print(f"  name: {item.get('name')}")
        print(f"  tags: {item.get('tags', [])}")
        print()
else:
    print(f"Error: {data.get('message')}")