from core.models import db, Customer, Item, Employee
from dotenv import load_dotenv

import requests
import time
import os

load_dotenv()
CLIENT_ID = os.getenv('ZOHO_CLIENT_ID')
CLIENT_SECRET = os.getenv('ZOHO_CLIENT_SECRET')
REFRESH_TOKEN = os.getenv('ZOHO_REFRESH_TOKEN')
ORG_ID = os.getenv('ZOHO_ORG_ID')
_token_cache = {"access_token": None, "expires_at": 0}


# Sync functions

def sync_customers():
    """Full customer sync — loops sync_customers_page until exhausted."""
    page = 1
    while True:
        result = sync_customers_page(page)
        if not result['has_more']:
            break
        page += 1


def sync_customers_page(page):
    """Sync one page of customers. Returns has_more boolean."""
    access_token = get_access_token()
    api_response = requests.get(
        "https://www.zohoapis.com/books/v3/contacts",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        params={"organization_id": ORG_ID, "contact_type": "customer", "per_page": 10, "page": page}
    )
    data = api_response.json()
    contacts = data.get('contacts', [])

    for contact in contacts:
        is_active = contact.get('status') != 'inactive'
        detail_response = requests.get(
            f"https://www.zohoapis.com/books/v3/contacts/{contact['contact_id']}",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={"organization_id": ORG_ID}
        )
        detail_data = detail_response.json()
        detail = detail_data.get('contact', {})
        billing = detail.get('billing_address', {})

        existing = Customer.query.get(contact['contact_id'])
        if existing:
            existing.customer_name = contact['contact_name']
            existing.email = contact.get('email', '')
            existing.phone = contact.get('phone', '')
            existing.address = billing.get('address', '')
            existing.city = billing.get('city', '')
            existing.state = billing.get('state', '')
            existing.country = billing.get('country', '')
            existing.zip = billing.get('zip', '')
            existing.is_active = is_active
        else:
            db.session.add(Customer(
                customer_id=contact['contact_id'],
                customer_name=contact['contact_name'],
                email=contact.get('email', ''),
                phone=contact.get('phone', ''),
                address=billing.get('address', ''),
                city=billing.get('city', ''),
                state=billing.get('state', ''),
                country=billing.get('country', ''),
                zip=billing.get('zip', ''),
                is_active=is_active
            ))

    db.session.commit()
    has_more = data.get('page_context', {}).get('has_more_page', False)
    return {'has_more': has_more, 'count': len(contacts)}


def sync_contracts_page(page, limit=None):
    """Sync one page of contracts with full detail. Returns has_more and synced count."""
    access_token = get_access_token()
    api_response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        params={"organization_id": ORG_ID, "per_page": 10, "page": page}
    )
    data = api_response.json()
    orders = data.get('salesorders', [])

    if limit is not None:
        orders = orders[:limit]

    for order in orders:
        detail = get_sales_order(order['salesorder_id'])
        upsert_contract_from_zoho(detail)

    has_more = data.get('page_context', {}).get('has_more_page', False)
    if limit is not None and len(orders) >= limit:
        has_more = False
    return {'has_more': has_more, 'count': len(orders)}


def sync_employees():
    access_token = get_access_token()
    api_response = requests.get(
        "https://www.zohoapis.com/books/v3/cm_employees",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        params={"organization_id": ORG_ID, "per_page": 200}
    )
    employees = api_response.json().get('module_records', [])

    for e in employees:
        office_val = e.get('cf_office_formatted') or e.get('cf_office') or ''
        if not office_val:
            keys = [k for k in e.keys() if 'office' in k.lower()]
            if keys:
                office_val = e.get(keys[0], '')
                print(f"  Employee office found under key '{keys[0]}': {office_val}")
            else:
                print(f"  Employee {e.get('cf_employees')} has no office field. Available keys: {list(e.keys())}")

        position_val = e.get('cf_position') or ''
        is_active = 'inactive' not in position_val.lower()

        existing = Employee.query.get(e.get('module_record_id'))
        if existing:
            existing.employee_name = e.get('cf_employees')
            existing.email = e.get('cf_email')
            existing.office = office_val
            existing.position = position_val
            existing.salesperson_id = e.get('cf_salesperson_id')
            existing.is_active = is_active
        else:
            new_employee = Employee(
                employee_id=e.get('module_record_id'),
                employee_name=e.get('cf_employees'),
                email=e.get('cf_email'),
                office=office_val,
                position=position_val,
                salesperson_id=e.get('cf_salesperson_id'),
                is_active=is_active
            )
            db.session.add(new_employee)

    db.session.commit()


def sync_items():
    items = get_items()
    for item in items:
        existing = Item.query.get(item['id'])
        if existing:
            existing.item_name = item['name']
            existing.description = item.get('description', '')
            existing.origin = item.get('origin', '')
            existing.pnl_group = item.get('pnl_group', '')
            existing.pnl_group_tag_option_id = item.get('pnl_group_tag_option_id', '')
            existing.is_active = item.get('is_active', True)
        else:
            new_item = Item(
                item_id=item['id'],
                item_name=item['name'],
                description=item.get('description', ''),
                origin=item.get('origin', ''),
                pnl_group=item.get('pnl_group', ''),
                pnl_group_tag_option_id=item.get('pnl_group_tag_option_id', ''),
                is_active=item.get('is_active', True)
            )
            db.session.add(new_item)
    db.session.commit()


# Getters

def get_items():
    access_token = get_access_token()
    items = []
    page = 1
    while True:
        api_response = requests.get(
            "https://www.zohoapis.com/books/v3/items",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={"organization_id": ORG_ID, "per_page": 200, "page": page}
        )
        data = api_response.json()
        page_items = data.get('items', [])
        items.extend(page_items)
        if not data.get('page_context', {}).get('has_more_page', False):
            break
        page += 1

    result = []
    for item in items:
        is_active = item.get("status") != "inactive"
        origin = item.get('cf_origin_location', '')
        pnl_group = ''
        pnl_group_tag_option_id = ''
        for tag in item.get('tags', []):
            if tag.get('tag_name') == 'P&L Group':
                pnl_group = tag.get('tag_option_name', '')
                pnl_group_tag_option_id = tag.get('tag_option_id', '')
                break

        result.append({
            "id": item["item_id"],
            "name": item["item_name"],
            "description": item.get("description", ""),
            "origin": origin,
            "pnl_group": pnl_group,
            "pnl_group_tag_option_id": pnl_group_tag_option_id,
            "is_active": is_active,
        })

    return result


def get_sales_order(salesorder_id):
    access_token = get_access_token()
    api_response = requests.get(
        f"https://www.zohoapis.com/books/v3/salesorders/{salesorder_id}",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        params={"organization_id": ORG_ID}
    )
    return api_response.json().get('salesorder', {})


def get_access_token():
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    api_response = requests.post(
        "https://accounts.zoho.com/oauth/v2/token",
        params={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": REFRESH_TOKEN,
        }
    )

    try:
        data = api_response.json()
    except Exception:
        raise RuntimeError("Failed to parse token response from Zoho")

    if 'access_token' not in data:
        raise RuntimeError(f"Failed to get access token: {data}")

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + 3500  # noqa

    return data["access_token"]


def get_sales_orders(page=1):
    coin = get_access_token()
    api_response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {coin}"},
        params={"organization_id": ORG_ID, "per_page": 200, "page": page}
    )
    return api_response.json().get('salesorders', [])


def get_next_test_number():
    access_token = get_access_token()
    api_response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        params={"organization_id": ORG_ID, "per_page": 200}
    )
    orders = api_response.json().get('salesorders', [])
    test_numbers = [
        o['salesorder_number'] for o in orders
        if o['salesorder_number'].startswith('TEST-')
    ]
    if not test_numbers:
        return 'TEST-001'
    numbers = []
    for n in test_numbers:
        try:
            numbers.append(int(n.split('-')[1]))
        except (ValueError, IndexError):
            pass
    next_num = max(numbers) + 1 if numbers else 1
    return f'TEST-{next_num:03d}'


def debug_reporting_tags():
    token = get_access_token()  # noqa
    orders = get_sales_orders(page=1)
    result = []
    for order in orders[:10]:
        so = get_sales_order(order['salesorder_id'])
        for item in so.get('line_items', []):
            tags = item.get('tags', [])
            if tags:
                result.append({
                    'salesorder_number': so.get('salesorder_number'),
                    'location_name': so.get('location_name'),
                    'tags': tags
                })
                break
    return result


def get_locations():
    return [
        {'branch_id': '4435369000015041009', 'branch_name': 'Head Office'},
        {'branch_id': '4435369000015041105', 'branch_name': 'FrontSeat'},
        {'branch_id': '4435369000015041141', 'branch_name': 'Argentina'},
        {'branch_id': '4435369000015041186', 'branch_name': 'Brazil'},
        {'branch_id': '4435369000015041222', 'branch_name': 'Shanghai'},
        {'branch_id': '4435369000015041258', 'branch_name': 'Australia'},
        {'branch_id': '4435369000015041294', 'branch_name': 'India'},
        {'branch_id': '4435369000015041905', 'branch_name': 'Turkey'},
        {'branch_id': '4435369000015041009', 'branch_name': 'Boulder'},
        {'branch_id': '', 'branch_name': 'S'},
        {'branch_id': '', 'branch_name': 'SBC'},
        {'branch_id': '', 'branch_name': 'SC'},
        {'branch_id': '', 'branch_name': 'Singapore'},
    ]


def get_office_tag_option_id(office_name):
    """Map office name to reporting tag option ID."""
    office_map = {
        'Argentina': '4435369000000088065',
        'Australia': '4435369000004707851',
        'Boulder': '4435369000000081153',
        'Brazil': '4435369000000088067',
        'Head Office': '4435369000000081153',
        'India': '4435369000000081157',
        'S': '4435369000000088075',
        'SBC': '4435369000000088077',
        'SC': '4435369000000088079',
        'Singapore': '4435369000000088083',
    }
    return office_map.get(office_name)


# Contract stuff

def submit_contract(form_data):
    coin = get_access_token()

    from core.models import Employee, Item
    second_broker_name = ''
    second_broker_emp_id = form_data.get('second_broker_employee_id', '')
    if second_broker_emp_id:
        second_emp = Employee.query.get(second_broker_emp_id)
        if second_emp:
            second_broker_name = second_emp.employee_name or ''

    salesperson_name = ''
    first_broker_emp_id = form_data.get('salesperson_employee_id', '')
    if first_broker_emp_id:
        first_emp = Employee.query.get(first_broker_emp_id)
        if first_emp:
            salesperson_name = first_emp.employee_name or ''

    custom_fields = [
        cf for cf in [
            {"api_name": "cf_buyer", "value": form_data.get('buyer_name')},
            {"api_name": "cf_item_contract_price", "value": form_data.get('commodity_rate')},
            {"api_name": "cf_trnspname", "value": form_data.get('transportation')},
            {"api_name": "cf_uom", "value": form_data.get('uom')},
            {"api_name": "cf_customer_ref", "value": form_data.get('seller_reference')},
            {"api_name": "cf_co_broker", "value": form_data.get('co_broker_name')},
            {"api_name": "cf_co_brokerage_rate", "value": form_data.get('co_brokerage_rate')},
            {"api_name": "cf_vessel_name", "value": form_data.get('vessel_name')},
        ] if cf['value'] and str(cf['value']).strip().lower() != 'none'
    ]
    if second_broker_name:
        custom_fields.append({"api_name": "cf_split_broker", "value": second_broker_name})
        second_broker_pct = form_data.get('second_broker_percentage', '')
        if second_broker_pct:
            try:
                pct_decimal = float(second_broker_pct) / 100
            except (ValueError, TypeError):
                pct_decimal = second_broker_pct
            custom_fields.append({"api_name": "cf_split_percentage", "value": pct_decimal})

    # Build line item with reporting tags
    line_item = {
        "item_id": form_data.get('commodity'),
        "quantity": form_data.get('quantity', 1),
        "rate": form_data.get('commission_rate'),
    }

    # Build tags array for Office and P&L Group
    tags = []

    # Add Office reporting tag from form location
    office_name = form_data.get('location_name', '')
    if office_name:
        office_tag_option_id = get_office_tag_option_id(office_name)
        if office_tag_option_id:
            tags.append({
                "tag_id": "4435369000000000333",
                "tag_name": "Office",
                "tag_option_id": office_tag_option_id,
                "tag_option_name": office_name,
            })
            print(f"DEBUG: Added Office tag for '{office_name}' with ID {office_tag_option_id}")

    # Add P&L Group reporting tag from item
    commodity_id = form_data.get('commodity')
    if commodity_id:
        item = Item.query.get(commodity_id)
        if item and item.pnl_group and item.pnl_group_tag_option_id:
            tags.append({
                "tag_id": "4435369000000000335",
                "tag_name": "P&L Group",
                "tag_option_id": item.pnl_group_tag_option_id,
                "tag_option_name": item.pnl_group,
            })

    print(f"DEBUG: final tags = {tags}")
    if tags:
        line_item['tags'] = tags

    payload = {
        "customer_id": form_data.get('seller'),
        "salesorder_number": get_next_test_number(),
        "date": form_data.get('contract_date'),
        "shipment_date": form_data.get('shipping_date_end'),
        "reference_number": form_data.get('booking_numbers_concat', '') or '',
        "notes": form_data.get('delivery_notes'),
        "location_id": form_data.get('location_id'),
        "line_items": [line_item],
        "custom_fields": custom_fields,
        "salesperson_name": salesperson_name,
    }

    print(f"DEBUG submit_contract: payload line_items = {payload['line_items']}")
    api_response = requests.post(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {coin}"},
        params={"organization_id": ORG_ID},
        json=payload
    )

    print(f"DEBUG submit_contract: response = {api_response.json()}")
    return api_response.json()


def update_contract(salesorder_id, form_data):
    access_token = get_access_token()

    from core.models import Employee, Item

    # Fetch existing contract to preserve existing tags
    existing_contract = get_sales_order(salesorder_id)
    existing_tags = existing_contract.get('line_items', [{}])[0].get('tags', []) if existing_contract else []

    second_broker_name = ''
    second_broker_emp_id = form_data.get('second_broker_employee_id', '')
    if second_broker_emp_id:
        second_emp = Employee.query.get(second_broker_emp_id)
        if second_emp:
            second_broker_name = second_emp.employee_name or ''

    salesperson_name = ''
    first_broker_emp_id = form_data.get('salesperson_employee_id', '')
    if first_broker_emp_id:
        first_emp = Employee.query.get(first_broker_emp_id)
        if first_emp:
            salesperson_name = first_emp.employee_name or ''

    custom_fields = [
        cf for cf in [
            {"api_name": "cf_buyer", "value": form_data.get('buyer_name')},
            {"api_name": "cf_item_contract_price", "value": form_data.get('commodity_rate')},
            {"api_name": "cf_trnspname", "value": form_data.get('transportation')},
            {"api_name": "cf_uom", "value": form_data.get('uom')},
            {"api_name": "cf_customer_ref", "value": form_data.get('seller_reference')},
            {"api_name": "cf_co_broker", "value": form_data.get('co_broker_name')},
            {"api_name": "cf_co_brokerage_rate", "value": form_data.get('co_brokerage_rate')},
            {"api_name": "cf_vessel_name", "value": form_data.get('vessel_name')},
        ] if cf['value'] and str(cf['value']).strip().lower() != 'none'
    ]
    if second_broker_name:
        custom_fields.append({"api_name": "cf_split_broker", "value": second_broker_name})
        second_broker_pct = form_data.get('second_broker_percentage', '')
        if second_broker_pct:
            try:
                pct_decimal = float(second_broker_pct) / 100
            except (ValueError, TypeError):
                pct_decimal = second_broker_pct
            custom_fields.append({"api_name": "cf_split_percentage", "value": pct_decimal})

    # Build line item with reporting tags
    line_item = {
        "item_id": form_data.get('commodity'),
        "quantity": form_data.get('quantity'),
        "rate": form_data.get('commission_rate'),
    }

    # Build tags array - merge existing tags with new ones from form
    tags = []

    # Add Office reporting tag from form location
    office_name = form_data.get('location_name', '')
    office_tag_added = False
    if office_name:
        office_tag_option_id = get_office_tag_option_id(office_name)
        if office_tag_option_id:
            tags.append({
                "tag_id": "4435369000000000333",
                "tag_name": "Office",
                "tag_option_id": office_tag_option_id,
                "tag_option_name": office_name,
            })
            office_tag_added = True

    # If no Office tag from form, try to preserve existing Office tag
    if not office_tag_added and existing_tags:
        for tag in existing_tags:
            if tag.get('tag_name') == 'Office':
                tags.append(tag)
                break

    # Add P&L Group reporting tag from item
    pnl_tag_added = False
    commodity_id = form_data.get('commodity')
    if commodity_id:
        item = Item.query.get(commodity_id)
        if item and item.pnl_group and item.pnl_group_tag_option_id:
            tags.append({
                "tag_id": "4435369000000000335",
                "tag_name": "P&L Group",
                "tag_option_id": item.pnl_group_tag_option_id,
                "tag_option_name": item.pnl_group,
            })
            pnl_tag_added = True

    # If no P&L Group tag from form, try to preserve existing P&L Group tag
    if not pnl_tag_added and existing_tags:
        for tag in existing_tags:
            if tag.get('tag_name') == 'P&L Group':
                tags.append(tag)
                break

    if tags:
        line_item['tags'] = tags

    payload = {
        "customer_id": form_data.get('seller'),
        "date": form_data.get('contract_date'),
        "shipment_date": form_data.get('shipping_date_end'),
        "reference_number": form_data.get('booking_numbers_concat', '') or '',
        "notes": form_data.get('delivery_notes'),
        "line_items": [line_item],
        "custom_fields": custom_fields,
        "salesperson_name": salesperson_name,
    }

    api_response = requests.put(
        f"https://www.zohoapis.com/books/v3/salesorders/{salesorder_id}",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        params={"organization_id": ORG_ID},
        json=payload
    )

    response_token = api_response.json()
    print(response_token)
    # Re-fetch full detail so upsert has complete custom_fields and line_items
    if response_token.get('code', 0) == 0:
        full_detail = get_sales_order(salesorder_id)
        if full_detail:
            response_token['salesorder'] = full_detail
    return response_token


def upsert_contract_from_zoho(detail):
    """Upsert all Zoho fields into the local Contract table from a salesorder detail dict."""
    from core.models import db, Contract
    salesorder_id = detail.get('salesorder_id', '')
    if not salesorder_id:
        return

    custom = {f['api_name']: f['value'] for f in detail.get('custom_fields', [])}
    line_items = detail.get('line_items', [])
    first_item = line_items[0] if line_items else {}

    # Office is stored on the Zoho side as a line-item reporting tag, not the
    # top-level branch/location. Read it back from the tag so that changes made
    # in Zoho (e.g. origin/office edits) sync into Quern's office field.
    office_tag_name = ''
    for tag in first_item.get('tags', []):
        if tag.get('tag_name') == 'Office':
            office_tag_name = tag.get('tag_option_name', '')
            break

    def safe_float(val):
        try:
            return float(val) if val not in (None, '', 'None') else None
        except (ValueError, TypeError):
            return None

    existing = Contract.query.get(salesorder_id)
    if not existing:
        existing = Contract(salesorder_id=salesorder_id)
        db.session.add(existing)

    existing.salesorder_number = detail.get('salesorder_number', '')
    existing.status = detail.get('status', '')
    existing.paid_status = detail.get('paid_status', '')
    existing.last_modified_time = detail.get('last_modified_time', '')
    existing.date = detail.get('date', '')
    existing.shipment_date = detail.get('shipment_date', '')
    # cf_shipment_end_date is not a Zoho custom field; it is local-only.
    # Do not overwrite it from the Zoho payload or every sync would wipe it.
    existing.customer_id = detail.get('customer_id', '')
    existing.customer_name = detail.get('customer_name', '')
    existing.cf_buyer = custom.get('cf_buyer', '')
    buyer_name = custom.get('cf_buyer', '')
    buyer_customer = Customer.query.filter_by(customer_name=buyer_name).first() if buyer_name else None
    existing.cf_buyer_id = buyer_customer.customer_id if buyer_customer else None
    existing.item_id = first_item.get('item_id', '')
    existing.item_name = first_item.get('name', '')
    existing.quantity = first_item.get('quantity')
    existing.rate = first_item.get('rate')
    existing.cf_item_contract_price = custom.get('cf_item_contract_price', '')
    existing.cf_trnspname = custom.get('cf_trnspname', '')
    existing.cf_uom = custom.get('cf_uom', '')
    existing.cf_customer_ref = custom.get('cf_customer_ref', '')
    existing.cf_co_broker = custom.get('cf_co_broker', '')
    existing.cf_co_brokerage_rate = safe_float(custom.get('cf_co_brokerage_rate'))
    existing.cf_split_broker = custom.get('cf_split_broker', '')
    existing.cf_split_percentage = safe_float(custom.get('cf_split_percentage'))
    existing.cf_vessel_name = custom.get('cf_vessel_name', '')
    existing.cf_origin_location = custom.get('cf_origin_location', '')
    existing.salesperson_name = detail.get('salesperson_name', '')
    existing.salesperson_id = detail.get('salesperson_id', '')
    existing.location_id = detail.get('location_id', '')
    # The Office reporting tag is authoritative for the office field. tag_option_id
    # lives in a separate namespace from branch/location IDs, so only the name is
    # used here; location_id stays sourced from the top-level payload.
    existing.location_name = office_tag_name or detail.get('location_name', '')
    existing.reference_number = detail.get('reference_number', '')
    existing.notes = detail.get('notes', '')
    existing.terms = detail.get('terms', '')

    db.session.commit()


def incremental_sync_page(page):
    """Sync one page of recently modified contracts. Returns has_more and count."""
    from core.models import SyncState
    from datetime import datetime, timezone, timedelta

    state = SyncState.query.filter_by(key='last_incremental_sync').first()
    if state:
        last_sync = state.value
    else:
        last_sync = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%S+0000')

    access_token = get_access_token()
    params = {
        "organization_id": ORG_ID,
        "per_page": 10,
        "page": page,
        "last_modified_time": last_sync
    }

    api_response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        params=params
    )
    data = api_response.json()
    orders = data.get('salesorders', [])

    for order in orders:
        salesorder_id = order['salesorder_id']
        detail = get_sales_order(salesorder_id)
        upsert_contract_from_zoho(detail)

    has_more = data.get('page_context', {}).get('has_more_page', False)

    # Only update timestamp on the final page
    if not has_more:
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+0000')
        if state:
            state.value = now
            state.updated_at = datetime.now(timezone.utc)
        else:
            db.session.add(SyncState(key='last_incremental_sync', value=now))
        db.session.commit()

    return {'has_more': has_more, 'count': len(orders)}


def contract_to_form_data(contract):
    """Convert a raw Books sales order dict to a flat form_data dict."""
    custom = {f['api_name']: f['value'] for f in contract.get('custom_fields', [])}
    line_items = contract.get('line_items', [{}])

    # cf_buyer stores the buyer name; resolve it to a customer_id for form prefill
    buyer_name = custom.get('cf_buyer', '')
    buyer_customer = Customer.query.filter_by(customer_name=buyer_name).first() if buyer_name else None
    buyer_id = buyer_customer.customer_id if buyer_customer else ''

    return {
        'seller': contract.get('customer_id', ''),
        'buyer': buyer_id,
        'contract_date': contract.get('date', ''),
        'shipping_date': contract.get('shipment_date', ''),
        'delivery_notes': contract.get('notes', ''),
        'terms': contract.get('terms', ''),
        'commodity': line_items[0].get('item_id', '') if line_items else '',
        'commission_rate': line_items[0].get('rate', '') if line_items else '',
        'quantity': line_items[0].get('quantity', '') if line_items else '',
        'commodity_rate': custom.get('cf_item_contract_price', ''),
        'transportation': custom.get('cf_trnspname', ''),
        'uom': custom.get('cf_uom', ''),
        'seller_reference': custom.get('cf_customer_ref', ''),
        'co_broker_name': custom.get('cf_co_broker', ''),
        'co_brokerage_rate': custom.get('cf_co_brokerage_rate', ''),
        'vessel_name': custom.get('cf_vessel_name', ''),
        # Zoho has no end-date field; this value only exists locally.
        'shipping_date_end': '',
        'location_id': contract.get('location_id', ''),
        'location_name': contract.get('location_name', ''),
    }


def contract_to_form_data_local(contract):
    """Convert a local Contract model instance to a flat form_data dict for prefilling."""
    from datetime import datetime

    buyer_id = contract.cf_buyer_id
    if not buyer_id and contract.cf_buyer:
        buyer_customer = Customer.query.filter_by(customer_name=contract.cf_buyer).first()
        buyer_id = buyer_customer.customer_id if buyer_customer else ''

    return {
        'seller': contract.customer_id or '',
        'buyer': buyer_id or '',
        'contract_date': datetime.now().strftime('%Y-%m-%d'),  # Duplicate defaults to today
        # NOTE: field names are inverted here — the form's "start" input
        # (shipping_date) is the dead one and "end" (shipping_date_end) is what
        # actually persists to contract.shipment_date. Storage wiring is left
        # as-is per current behaviour; only the duplicate prefill is fixed so
        # both inputs carry the stored date instead of start coming over blank.
        # TODO: un-invert the shipping_date / shipping_date_end naming properly.
        'shipping_date': contract.shipment_date or contract.cf_shipment_end_date or '',
        'shipping_date_end': contract.shipment_date or contract.cf_shipment_end_date or '',
        'delivery_notes': contract.notes or '',
        'terms': contract.terms or '',
        'commodity': contract.item_id or '',
        'commission_rate': contract.rate or '',
        'quantity': contract.quantity or '',
        'commodity_rate': contract.cf_item_contract_price or '',
        'transportation': contract.cf_trnspname or '',
        'uom': contract.cf_uom or '',
        'seller_reference': '',  # Drop reference numbers on duplicate
        'co_broker_name': contract.cf_co_broker or '',
        'co_brokerage_rate': contract.cf_co_brokerage_rate or '',
        'vessel_name': '',  # Omit vessel name on duplicate
        'location_id': contract.location_id or '',
        'location_name': contract.location_name or '',
        'origin': contract.origin or '',
    }


if __name__ == '__main__':
    token = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": ORG_ID, "per_page": 1}
    )
    print(response.json())