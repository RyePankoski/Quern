from core.models import db, Customer, Item, Employee
from dotenv import load_dotenv

import requests
import time
import json
import os

load_dotenv()
CLIENT_ID = os.getenv('ZOHO_CLIENT_ID')
CLIENT_SECRET = os.getenv('ZOHO_CLIENT_SECRET')
REFRESH_TOKEN = os.getenv('ZOHO_REFRESH_TOKEN')
ORG_ID = os.getenv('ZOHO_ORG_ID')
_token_cache = {"access_token": None, "expires_at": 0}
_TOKEN_FILE = "../.token_cache"


# Sync functions

def sync_customers():
    token = get_access_token()
    page = 1

    contract_no = 0

    while True:
        response = requests.get(
            "https://www.zohoapis.com/books/v3/contacts",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            params={"organization_id": ORG_ID, "contact_type": "customer", "per_page": 200, "page": page}
        )
        contacts = response.json().get('contacts', [])

        if not contacts:
            break

        for contact in contacts:
            if contact.get('status') == 'inactive':
                continue
            contract_no += 1
            print(f"Syncing {contact['contact_name']}... + {contract_no}")
            # Fetch full contact detail for address
            detail_response = requests.get(
                f"https://www.zohoapis.com/books/v3/contacts/{contact['contact_id']}",
                headers={"Authorization": f"Zoho-oauthtoken {token}"},
                params={"organization_id": ORG_ID}
            )
            detail_data = detail_response.json()
            if 'contact' not in detail_data:
                print(f"  Warning: no contact detail for {contact['contact_name']}: {detail_data}")
                detail = {}
            else:
                detail = detail_data['contact']
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
                    zip=billing.get('zip', '')
                ))

        db.session.commit()
        page += 1


def sync_employees():
    token = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/cm_employees",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": ORG_ID, "per_page": 200}
    )
    employees = response.json().get('module_records', [])

    for e in employees:
        # Try both the formatted and raw key names for the office field —
        # Zoho custom module responses use _formatted suffix for lookup/dropdown
        # display values, but the actual key can vary. Log what we receive so
        # mismatches can be caught.
        office_val = e.get('cf_office_formatted') or e.get('cf_office') or ''
        if not office_val:
            keys = [k for k in e.keys() if 'office' in k.lower()]
            if keys:
                office_val = e.get(keys[0], '')
                print(f"  Employee office found under key '{keys[0]}': {office_val}")
            else:
                print(f"  Employee {e.get('cf_employees')} has no office field. Available keys: {list(e.keys())}")

        existing = Employee.query.get(e.get('module_record_id'))
        if existing:
            existing.employee_name = e.get('cf_employees')
            existing.email = e.get('cf_email')
            existing.office = office_val
            existing.position = e.get('cf_position')
            existing.salesperson_id = e.get('cf_salesperson_id')
        else:
            new_employee = Employee(
                employee_id=e.get('module_record_id'),
                employee_name=e.get('cf_employees'),
                email=e.get('cf_email'),
                office=office_val,
                position=e.get('cf_position'),
                salesperson_id=e.get('cf_salesperson_id')
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
        else:
            new_item = Item(
                item_id=item['id'],
                item_name=item['name'],
                description=item.get('description', ''),
                origin=item.get('origin', ''),
                pnl_group=item.get('pnl_group', '')
            )
            db.session.add(new_item)
    db.session.commit()


# Getters

def get_items():
    coin = get_access_token()
    items = []
    page = 1
    while True:
        response = requests.get(
            "https://www.zohoapis.com/books/v3/items",
            headers={"Authorization": f"Zoho-oauthtoken {coin}"},
            params={"organization_id": ORG_ID, "per_page": 200, "page": page}
        )
        data = response.json()
        page_items = data.get('items', [])
        items.extend(page_items)
        if not data.get('page_context', {}).get('has_more_page', False):
            break
        page += 1

    result = []
    for item in items:
        if item.get("status") == "inactive":
            continue

        # Pull origin and pnl_group from custom fields if present
        custom_fields = {cf['api_name']: cf.get('value', '') for cf in item.get('custom_fields', [])}
        # Reporting tags: pnl_group is expected under a reporting tag named 'PnL Group'
        # Adjust tag_name below to match the exact name in your Books account.
        reporting_tags = item.get('reporting_tags', [])
        pnl_group = ''
        for tag in reporting_tags:
            if tag.get('tag_name', '').lower() in ('pnl group', 'pnl_group', 'p&l group'):
                tag_options = tag.get('tag_option_name', '') or tag.get('value', '')
                pnl_group = tag_options
                break

        origin = custom_fields.get('cf_origin', '') or custom_fields.get('cf_item_origin', '')

        result.append({
            "id": item["item_id"],
            "name": item["item_name"],
            "description": item.get("description", ""),
            "origin": origin,
            "pnl_group": pnl_group,
        })

    return result


def get_customers():
    coin = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/contacts",
        headers={"Authorization": f"Zoho-oauthtoken {coin}"},
        params={"organization_id": ORG_ID, "contact_type": "customer", "per_page": 200}
    )
    contacts = response.json().get('contacts', [])
    return [{"id": contact["contact_id"], "name": contact["contact_name"]} for contact in contacts]


def get_sales_order(salesorder_id):
    token = get_access_token()
    response = requests.get(
        f"https://www.zohoapis.com/books/v3/salesorders/{salesorder_id}",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": ORG_ID}
    )
    return response.json().get('salesorder', {})


def get_access_token():
    try:
        if os.path.exists(_TOKEN_FILE):
            with open(_TOKEN_FILE) as f:
                cache = json.load(f)
            if time.time() < cache.get("expires_at", 0):
                return cache["access_token"]
    except (json.JSONDecodeError, KeyError, IOError):
        pass  # Cache is corrupt or unreadable, fall through to refresh

    response = requests.post(
        "https://accounts.zoho.com/oauth/v2/token",
        params={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": REFRESH_TOKEN,
        }
    )

    try:
        data = response.json()
    except Exception:
        raise RuntimeError("Failed to parse token response from Zoho")

    if 'access_token' not in data:
        raise RuntimeError(f"Failed to get access token: {data}")

    cache = {
        "access_token": data["access_token"],
        "expires_at": time.time() + 3500
    }

    try:
        with open(_TOKEN_FILE, "w") as f:
            json.dump(cache, f)
    except IOError as e:
        pass  # Non-fatal — token still works this session, just won't be cached

    return data["access_token"]


def get_sales_orders(page=1):
    coin = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {coin}"},
        params={"organization_id": ORG_ID, "per_page": 200, "page": page}
    )
    return response.json().get('salesorders', [])


def get_sales_orders_for_item(item_id):
    """
    Fetch sales orders that contain a specific item.
    Zoho Books supports filtering by item_id on the salesorders list endpoint.
    Falls back to an empty list if the API doesn't support it.
    """
    coin = get_access_token()
    orders = []
    page = 1
    while True:
        response = requests.get(
            "https://www.zohoapis.com/books/v3/salesorders",
            headers={"Authorization": f"Zoho-oauthtoken {coin}"},
            params={"organization_id": ORG_ID, "per_page": 200, "page": page, "item_id": item_id}
        )
        data = response.json()
        page_orders = data.get('salesorders', [])
        orders.extend(page_orders)
        if not data.get('page_context', {}).get('has_more_page', False):
            break
        page += 1
    return orders


def get_next_test_number():
    token = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": ORG_ID, "per_page": 200}
    )
    orders = response.json().get('salesorders', [])
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
        except:
            pass
    next_num = max(numbers) + 1 if numbers else 1
    return f'TEST-{next_num:03d}'


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
    ]


# Contract stuff

def submit_contract(form_data):
    coin = get_access_token()

    # Concatenate booking numbers into customer_notes
    booking_numbers = form_data.get('booking_numbers_concat', '')

    # Resolve second broker to Zoho salesperson ID
    second_broker_zoho_id = ''
    second_broker_emp_id = form_data.get('second_broker_employee_id', '')
    if second_broker_emp_id:
        from core.models import Employee
        second_emp = Employee.query.get(second_broker_emp_id)
        if second_emp and second_emp.salesperson_id:
            second_broker_zoho_id = second_emp.salesperson_id

    # Resolve first broker to Zoho salesperson ID
    salesperson_zoho_id = ''
    first_broker_emp_id = form_data.get('salesperson_employee_id', '')
    if first_broker_emp_id:
        from core.models import Employee
        first_emp = Employee.query.get(first_broker_emp_id)
        if first_emp and first_emp.salesperson_id:
            salesperson_zoho_id = first_emp.salesperson_id

    custom_fields = [
        {"api_name": "cf_buyer", "value": form_data.get('buyer_name')},
        {"api_name": "cf_item_contract_price", "value": form_data.get('commodity_rate')},
        {"api_name": "cf_vessel_name", "value": form_data.get('vessel_name')},
        {"api_name": "cf_trnspname", "value": form_data.get('transportation')},
        {"api_name": "cf_uom", "value": form_data.get('uom')},
        {"api_name": "cf_customer_ref", "value": form_data.get('seller_reference')},
        {"api_name": "cf_co_broker", "value": form_data.get('co_broker_name')},
        {"api_name": "cf_co_brokerage_rate", "value": form_data.get('co_brokerage_rate')},
        {"api_name": "cf_shipping_date_end", "value": form_data.get('shipping_date_end')},
    ]
    if second_broker_zoho_id:
        custom_fields.append({"api_name": "cf_split_broker", "value": second_broker_zoho_id})

    payload = {
        "customer_id": form_data.get('seller'),
        "salesorder_number": get_next_test_number(),
        "date": form_data.get('contract_date'),
        "shipment_date": form_data.get('shipping_date'),
        "notes": form_data.get('delivery_notes'),
        "customer_notes": booking_numbers,
        "terms": form_data.get('terms'),
        "location_id": form_data.get('location_id'),
        "line_items": [
            {
                "item_id": form_data.get('commodity'),
                "quantity": form_data.get('quantity', 1),
                "rate": form_data.get('commission_rate'),
            }
        ],
        "custom_fields": custom_fields,
    }

    if salesperson_zoho_id:
        payload["salesperson_id"] = salesperson_zoho_id

    response = requests.post(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {coin}"},
        params={"organization_id": ORG_ID},
        json=payload
    )

    print(response.json())
    return response.json()


def update_contract(salesorder_id, form_data):
    token = get_access_token()

    # Concatenate booking numbers into customer_notes
    booking_numbers = form_data.get('booking_numbers_concat', '')

    # Resolve second broker to Zoho salesperson ID
    second_broker_zoho_id = ''
    second_broker_emp_id = form_data.get('second_broker_employee_id', '')
    if second_broker_emp_id:
        from core.models import Employee
        second_emp = Employee.query.get(second_broker_emp_id)
        if second_emp and second_emp.salesperson_id:
            second_broker_zoho_id = second_emp.salesperson_id

    # Resolve first broker to Zoho salesperson ID
    salesperson_zoho_id = ''
    first_broker_emp_id = form_data.get('salesperson_employee_id', '')
    if first_broker_emp_id:
        from core.models import Employee
        first_emp = Employee.query.get(first_broker_emp_id)
        if first_emp and first_emp.salesperson_id:
            salesperson_zoho_id = first_emp.salesperson_id

    custom_fields = [
        {"api_name": "cf_buyer", "value": form_data.get('buyer_name')},
        {"api_name": "cf_item_contract_price", "value": form_data.get('commodity_rate')},
        {"api_name": "cf_vessel_name", "value": form_data.get('vessel_name')},
        {"api_name": "cf_trnspname", "value": form_data.get('transportation')},
        {"api_name": "cf_uom", "value": form_data.get('uom')},
        {"api_name": "cf_customer_ref", "value": form_data.get('seller_reference')},
        {"api_name": "cf_co_broker", "value": form_data.get('co_broker_name')},
        {"api_name": "cf_co_brokerage_rate", "value": form_data.get('co_brokerage_rate')},
        {"api_name": "cf_shipping_date_end", "value": form_data.get('shipping_date_end')},
    ]
    if second_broker_zoho_id:
        custom_fields.append({"api_name": "cf_split_broker", "value": second_broker_zoho_id})

    payload = {
        "customer_id": form_data.get('seller'),
        "date": form_data.get('contract_date'),
        "shipment_date": form_data.get('shipping_date'),
        "notes": form_data.get('delivery_notes'),
        "customer_notes": booking_numbers,
        "terms": form_data.get('terms'),
        "line_items": [
            {
                "item_id": form_data.get('commodity'),
                "quantity": form_data.get('quantity'),
                "rate": form_data.get('commission_rate'),
            }
        ],
        "custom_fields": custom_fields,
    }

    if salesperson_zoho_id:
        payload["salesperson_id"] = salesperson_zoho_id

    response = requests.put(
        f"https://www.zohoapis.com/books/v3/salesorders/{salesorder_id}",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": ORG_ID},
        json=payload
    )

    print(response.json())
    return response.json()


def contract_to_form_data(contract):
    """Convert a raw Books sales order dict to a flat form_data dict."""
    custom = {f['api_name']: f['value'] for f in contract.get('custom_fields', [])}
    line_items = contract.get('line_items', [{}])
    return {
        'seller': contract.get('customer_id', ''),
        'buyer': custom.get('cf_buyer', ''),
        'contract_date': contract.get('date', ''),
        'shipping_date': contract.get('shipment_date', ''),
        'delivery_notes': contract.get('notes', ''),
        'terms': contract.get('terms', ''),
        'commodity': line_items[0].get('item_id', '') if line_items else '',
        'commission_rate': line_items[0].get('rate', '') if line_items else '',
        'quantity': line_items[0].get('quantity', '') if line_items else '',
        'commodity_rate': custom.get('cf_item_contract_price', ''),
        'vessel_name': custom.get('cf_vessel_name', ''),
        'transportation': custom.get('cf_trnspname', ''),
        'uom': custom.get('cf_uom', ''),
        'seller_reference': custom.get('cf_customer_ref', ''),
        'co_broker_name': custom.get('cf_co_broker', ''),
        'co_brokerage_rate': custom.get('cf_co_brokerage_rate', ''),
        'shipping_date_end': custom.get('cf_shipping_date_end', ''),
        'location_id': contract.get('location_id', ''),
        'location_name': contract.get('location_name', ''),
        # salesperson_employee_id and second_broker_employee_id are not stored here
        # because they come from the broker subform on submit/update, not from Books.
        # booking_numbers_concat is also assembled at submit/update time from form data.
    }


if __name__ == '__main__':
    token = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": ORG_ID, "per_page": 1}
    )
    print(response.json())