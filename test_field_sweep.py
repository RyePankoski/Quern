#!/usr/bin/env python3
"""
Field sweep: compare what Zoho returns vs what's stored locally, field by field.
Identifies which contract fields aren't coming over correctly.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

from app import app
from core.models import Contract


def get_access_token():
    from core.zoho import get_access_token as zoho_get_access_token
    return zoho_get_access_token()


access_token = get_access_token()
org_id = os.getenv('ZOHO_ORG_ID')

# Fields to compare: (local_attr, zoho_location, zoho_key)
# zoho_location: 'detail', 'custom', or 'line_item'
FIELD_MAP = [
    ('salesorder_number', 'detail', 'salesorder_number'),
    ('status', 'detail', 'status'),
    ('date', 'detail', 'date'),
    ('shipment_date', 'detail', 'shipment_date'),
    ('customer_name', 'detail', 'customer_name'),
    ('cf_buyer', 'custom', 'cf_buyer'),
    ('item_name', 'line_item', 'name'),
    ('quantity', 'line_item', 'quantity'),
    ('rate', 'line_item', 'rate'),
    ('cf_item_contract_price', 'custom', 'cf_item_contract_price'),
    ('cf_trnspname', 'custom', 'cf_trnspname'),
    ('cf_uom', 'custom', 'cf_uom'),
    ('cf_customer_ref', 'custom', 'cf_customer_ref'),
    ('cf_co_broker', 'custom', 'cf_co_broker'),
    ('cf_vessel_name', 'custom', 'cf_vessel_name'),
    ('cf_origin_location', 'custom', 'cf_origin_location'),
    ('salesperson_name', 'detail', 'salesperson_name'),
    ('location_name', 'detail', 'location_name'),
    ('reference_number', 'detail', 'reference_number'),
    ('cf_shipment_end_date', 'custom', 'cf_shipment_end_date'),
]


def get_zoho_value(detail, location, key):
    if location == 'detail':
        return detail.get(key)
    elif location == 'custom':
        custom = {f['api_name']: f['value'] for f in detail.get('custom_fields', [])}
        return custom.get(key)
    elif location == 'line_item':
        line_items = detail.get('line_items', [])
        return line_items[0].get(key) if line_items else None
    return None


with app.app_context():
    # Sample 15 contracts that exist locally
    local_contracts = Contract.query.limit(15).all()

    # Track mismatches per field
    field_issues = {fm[0]: {'zoho_has_local_empty': 0, 'match': 0, 'both_empty': 0, 'mismatch': 0} for fm in FIELD_MAP}

    print(f"Sweeping {len(local_contracts)} contracts...\n")

    for c in local_contracts:
        so_id = c.salesorder_id
        # Fetch full detail from Zoho
        resp = requests.get(
            f"https://www.zohoapis.com/books/v3/salesorders/{so_id}",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={"organization_id": org_id}
        )
        data = resp.json()
        if data.get('code') != 0:
            print(f"  Skip {so_id}: {data.get('message')}")
            continue
        detail = data.get('salesorder', {})

        for local_attr, location, key in FIELD_MAP:
            zoho_val = get_zoho_value(detail, location, key)
            local_val = getattr(c, local_attr, None)

            zoho_empty = zoho_val in (None, '', 'None')
            local_empty = local_val in (None, '', 'None')

            if zoho_empty and local_empty:
                field_issues[local_attr]['both_empty'] += 1
            elif not zoho_empty and local_empty:
                field_issues[local_attr]['zoho_has_local_empty'] += 1
            elif str(zoho_val).strip() == str(local_val).strip():
                field_issues[local_attr]['match'] += 1
            else:
                field_issues[local_attr]['mismatch'] += 1

    print(f"{'Field':<28} {'Match':<7} {'ZohoHas/LocalEmpty':<20} {'Mismatch':<10} {'BothEmpty':<10}")
    print("=" * 80)
    for local_attr, location, key in FIELD_MAP:
        s = field_issues[local_attr]
        flag = '  <-- DROPPING DATA' if s['zoho_has_local_empty'] > 0 else ''
        print(
            f"{local_attr:<28} {s['match']:<7} {s['zoho_has_local_empty']:<20} {s['mismatch']:<10} {s['both_empty']:<10}{flag}")