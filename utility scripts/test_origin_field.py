#!/usr/bin/env python3
"""Check how cf_origin_location is stored in a Zoho contract."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

def get_access_token():
    from core.zoho import get_access_token as zoho_get_access_token
    return zoho_get_access_token()

salesorder_id = input("Enter a salesorder_id that has an origin set: ")

access_token = get_access_token()
org_id = os.getenv('ZOHO_ORG_ID')

api_response = requests.get(
    f"https://www.zohoapis.com/books/v3/salesorders/{salesorder_id}",
    headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
    params={"organization_id": org_id}
)

data = api_response.json()
so = data.get('salesorder', {})

print("\n=== Searching for origin ===")
# Check top-level
print(f"Top-level cf_origin_location: {so.get('cf_origin_location', 'NOT FOUND')}")

# Check custom_field_hash
cfh = so.get('custom_field_hash', {})
print(f"\ncustom_field_hash origin keys:")
for k, v in cfh.items():
    if 'origin' in k.lower():
        print(f"  {k}: {v}")

# Check custom_fields array
print(f"\ncustom_fields array origin entries:")
for cf in so.get('custom_fields', []):
    if 'origin' in cf.get('api_name', '').lower() or 'origin' in cf.get('label', '').lower():
        print(f"  api_name={cf.get('api_name')}, label={cf.get('label')}, value={cf.get('value')}")

# Dump all custom field api_names for reference
print(f"\nAll custom_fields api_names:")
for cf in so.get('custom_fields', []):
    print(f"  {cf.get('api_name')}: {cf.get('value')}")