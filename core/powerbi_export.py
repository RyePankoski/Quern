"""
Power BI Excel export function for daily snapshots.
Exports contracts data to an Excel file for Power BI ingestion.
"""
import os
from datetime import datetime
from io import BytesIO
import pandas as pd
from core.models import Contract, BrokerCommission, Employee, db


def export_contracts_to_excel(output_path=None):
    """
    Export all contracts and related broker commission data to an Excel file.

    Args:
        output_path: Optional file path. If None, uses /mnt/quern-data/contracts_export.xlsx

    Returns:
        Tuple of (file_path, row_count) on success, or (None, error_message) on failure.
    """
    if output_path is None:
        output_path = '/mnt/quern-data/contracts_export.xlsx'

    try:
        # Query all contracts
        contracts = Contract.query.all()

        if not contracts:
            return output_path, "No contracts to export"

        # Build contracts DataFrame
        contracts_data = []
        for contract in contracts:
            contracts_data.append({
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
            })

        contracts_df = pd.DataFrame(contracts_data)

        # Build broker commissions DataFrame (pivoted by contract)
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

        # Flatten commissions into contract rows
        if commissions_data:
            for idx, row in contracts_df.iterrows():
                so_id = row['Salesorder ID']
                if so_id in commissions_data:
                    for key, value in commissions_data[so_id].items():
                        if key not in contracts_df.columns:
                            contracts_df[key] = None
                        contracts_df.at[idx, key] = value

        # Write to Excel
        contracts_df.to_excel(output_path, sheet_name='Contracts', index=False)

        row_count = len(contracts_df)
        return output_path, row_count

    except Exception as e:
        return None, f"Export failed: {str(e)}"