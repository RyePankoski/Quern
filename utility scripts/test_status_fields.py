#!/usr/bin/env python3
"""Sample contracts to see what status field values Zoho returns."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()


def get_access_token():
    from core.zoho import get_access_token as zoho_get_access_token
    return zoho_get_access_token()


access_token = get_access_token()
org_id = os.getenv('ZOHO_ORG_ID')

# Get list of contract IDs
api_response = requests.get(
    "https://www.zohoapis.com/books/v3/salesorders",
    headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
    params={"organization_id": org_id, "page": 1, "per_page": 30}
)
data = api_response.json()
salesorders = data.get('salesorders', [])

print(f"Sampling {len(salesorders)} contracts for status fields...\n")
print(
    f"{'SO Number':<15} {'status':<12} {'order_status':<14} {'invoiced_status':<18} {'paid_status':<12} {'shipped_status':<12}")
print("=" * 95)

status_combos = set()

for so in salesorders:
    so_id = so.get('salesorder_id')
    # Individual fetch for full detail
    detail_resp = requests.get(
        f"https://www.zohoapis.com/books/v3/salesorders/{so_id}",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        params={"organization_id": org_id}
    )
    detail = detail_resp.json().get('salesorder', {})

    num = detail.get('salesorder_number', '')[:14]
    status = detail.get('status', '')[:11]
    order_status = detail.get('order_status', '')[:13]
    invoiced = detail.get('invoiced_status', '')[:17]
    paid = detail.get('paid_status', '')[:11]
    shipped = detail.get('shipped_status', '')[:11]

    print(f"{num:<15} {status:<12} {order_status:<14} {invoiced:<18} {paid:<12} {shipped:<12}")
    status_combos.add((status, order_status, invoiced, paid, shipped))

print("\n\nUnique combinations found:")
for combo in sorted(status_combos):
    print(f"  status={combo[0]!r}, order={combo[1]!r}, invoiced={combo[2]!r}, paid={combo[3]!r}, shipped={combo[4]!r}")