#!/usr/bin/env python3
"""Compare local DB status vs Zoho status for contracts."""

from app import app
from core.models import Contract

with app.app_context():
    contracts = Contract.query.limit(30).all()

    print(f"Local DB status values:\n")
    print(f"{'SO Number':<15} {'Local status':<15}")
    print("=" * 35)

    status_counts = {}
    for c in contracts:
        print(f"{c.salesorder_number or '':<15} {c.status or '(empty)':<15}")
        status_counts[c.status or '(empty)'] = status_counts.get(c.status or '(empty)', 0) + 1

    print(f"\n\nStatus value counts (all contracts):")
    all_contracts = Contract.query.all()
    all_counts = {}
    for c in all_contracts:
        s = c.status or '(empty)'
        all_counts[s] = all_counts.get(s, 0) + 1

    for status, count in sorted(all_counts.items()):
        print(f"  {status:<20} {count}")