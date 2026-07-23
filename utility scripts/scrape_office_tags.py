#!/usr/bin/env python
"""
Scrape Office reporting tag option IDs from Zoho contracts.
Must fetch INDIVIDUAL contracts (list endpoint omits line_items).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from core.zoho import get_sales_orders, get_sales_order


def main():
    with app.app_context():
        print("Fetching contracts from list (to get IDs)...")
        office_tags = {}
        contracts_checked = 0

        # Get contract IDs from list
        page = 1
        while True:
            list_contracts = get_sales_orders(page=page)
            if not list_contracts:
                break

            print(f"\nPage {page}: Processing {len(list_contracts)} contracts...")

            for contract_summary in list_contracts:
                salesorder_id = contract_summary.get('salesorder_id')
                if not salesorder_id:
                    continue

                # Fetch individual contract to get tags (list endpoint omits line_items)
                full_contract = get_sales_order(salesorder_id)
                contracts_checked += 1

                for line_item in full_contract.get('line_items', []):
                    for tag in line_item.get('tags', []):
                        if tag.get('tag_name') == 'Office':
                            office_name = tag.get('tag_option_name')
                            option_id = tag.get('tag_option_id')
                            if office_name and option_id and office_name not in office_tags:
                                office_tags[office_name] = option_id
                                print(f"  Found: '{office_name}': '{option_id}',")

            page += 1
            if page > 10:  # Limit to avoid too many API calls
                print(f"\nStopped at page {page} (limit reached)")
                break

        print("\n" + "=" * 60)
        print("Office tags found (paste into get_office_tag_option_id):")
        print("=" * 60)
        for name, id in sorted(office_tags.items()):
            print(f"    '{name}': '{id}',")

        print("\n" + "=" * 60)
        print(f"Checked {contracts_checked} individual contracts")
        print(f"Total unique offices: {len(office_tags)}")
        print("=" * 60)


if __name__ == '__main__':
    main()