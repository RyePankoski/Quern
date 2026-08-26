"""
Power BI data export function for daily snapshots.
Exports contracts data to a CSV file for Power BI ingestion.
"""
import csv
import os
from datetime import datetime

try:
    from .models import Contract, BrokerCommission, Employee, db
except ImportError:
    from models import Contract, BrokerCommission, Employee, db


def export_contracts_to_excel(output_path=None):
    """
    Export all contracts and related broker commission data to a CSV file.

    Args:
        output_path: Optional file path. If None, uses /mnt/quern-data/contracts_export.csv

    Returns:
        Tuple of (file_path, row_count) on success, or (None, error_message) on failure.
    """
    if output_path is None:
        output_path = '/mnt/quern-data/contracts_export.csv'

    try:
        # Query all contracts
        contracts = Contract.query.all()

        if not contracts:
            return output_path, "No contracts to export"

        # Build broker commissions lookup
        commissions_data = {}
        commission_rows = BrokerCommission.query.all()

        for commission in commission_rows:
            so_id = commission.books_sales_order_id
            if so_id not in commissions_data:
                commissions_data[so_id] = {}

            employee = Employee.query.get(commission.employee_id)
            employee_name = employee.employee_name if employee else f"Employee {commission.employee_id}"

            commissions_data[so_id][f'Broker: {employee_name}'] = commission.employee_id
            commissions_data[so_id][f'Broker % {employee_name}'] = commission.percentage
            commissions_data[so_id][f'Broker $ {employee_name}'] = commission.amount

        # Collect all unique commission columns
        all_commission_cols = set()
        for commissions in commissions_data.values():
            all_commission_cols.update(commissions.keys())
        all_commission_cols = sorted(all_commission_cols)

        # Define CSV headers
        headers = [
            'Salesorder ID', 'Salesorder Number', 'Status', 'Paid Status',
            'Date', 'Shipment Date', 'Shipment End Date',
            'Seller (Customer Name)', 'Seller ID',
            'Buyer', 'Buyer ID',
            'Item', 'Item ID', 'Quantity', 'Rate', 'Total',
            'Contract Price', 'Transport Name', 'UOM', 'Customer Ref',
            'Co-Broker', 'Co-Brokerage Rate', 'Split Broker', 'Split Percentage',
            'Vessel Name', 'Origin Location',
            'Salesperson', 'Salesperson ID', 'Location', 'Location ID',
            'Reference Number', 'Notes', 'Terms',
            'Buyer Reference', 'Is Declined', 'Packing', 'Origin',
            'PIC Employee ID', 'Paid Date', 'Last Modified'
        ] + all_commission_cols

        # Write to CSV
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers, restval='')
            writer.writeheader()

            for contract in contracts:
                row = {
                    'Salesorder ID': contract.salesorder_id,
                    'Salesorder Number': contract.salesorder_number,
                    'Status': contract.status,
                    'Paid Status': contract.paid_status,
                    'Date': contract.date,
                    'Shipment Date': contract.shipment_date,
                    'Shipment End Date': contract.cf_shipment_end_date,
                    'Seller (Customer Name)': contract.customer_name,
                    'Seller ID': contract.customer_id,
                    'Buyer': contract.cf_buyer,
                    'Buyer ID': contract.cf_buyer_id,
                    'Item': contract.item_name,
                    'Item ID': contract.item_id,
                    'Quantity': contract.quantity,
                    'Rate': contract.rate,
                    'Total': contract.total,
                    'Contract Price': contract.cf_item_contract_price,
                    'Transport Name': contract.cf_trnspname,
                    'UOM': contract.cf_uom,
                    'Customer Ref': contract.cf_customer_ref,
                    'Co-Broker': contract.cf_co_broker,
                    'Co-Brokerage Rate': contract.cf_co_brokerage_rate,
                    'Split Broker': contract.cf_split_broker,
                    'Split Percentage': contract.cf_split_percentage,
                    'Vessel Name': contract.cf_vessel_name,
                    'Origin Location': contract.cf_origin_location,
                    'Salesperson': contract.salesperson_name,
                    'Salesperson ID': contract.salesperson_id,
                    'Location': contract.location_name,
                    'Location ID': contract.location_id,
                    'Reference Number': contract.reference_number,
                    'Notes': contract.notes,
                    'Terms': contract.terms,
                    'Buyer Reference': contract.buyer_reference,
                    'Is Declined': contract.is_declined,
                    'Packing': contract.packing,
                    'Origin': contract.origin,
                    'PIC Employee ID': contract.pic_employee_id,
                    'Paid Date': contract.paid_date,
                    'Last Modified': contract.last_modified_time,
                }

                # Add commission columns for this contract
                if contract.salesorder_id in commissions_data:
                    row.update(commissions_data[contract.salesorder_id])

                writer.writerow(row)

        row_count = len(contracts)
        return output_path, row_count

    except Exception as e:
        return None, f"Export failed: {str(e)}"