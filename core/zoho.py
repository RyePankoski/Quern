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
            detail = detail_response.json().get('contact', {})
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
        existing = Employee.query.get(e.get('module_record_id'))
        if existing:
            existing.employee_name = e.get('cf_employees')
            existing.email = e.get('cf_email')
            existing.office = e.get('cf_office_formatted')
            existing.position = e.get('cf_position')
            existing.salesperson_id = e.get('cf_salesperson_id')
        else:
            new_employee = Employee(
                employee_id=e.get('module_record_id'),
                employee_name=e.get('cf_employees'),
                email=e.get('cf_email'),
                office=e.get('cf_office_formatted'),
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
        else:
            new_item = Item(
                item_id=item['id'],
                item_name=item['name'],
                description=item.get('description', '')
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
    return [{"id": item["item_id"], "name": item["item_name"], "description": item.get("description", "")} for item in
            items if item.get("status") != "inactive"]


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
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

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

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + 3500

    return data["access_token"]


def get_sales_orders(page=1):
    coin = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {coin}"},
        params={"organization_id": ORG_ID, "per_page": 200, "page": page}
    )
    return response.json().get('salesorders', [])


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

    payload = {
        "customer_id": form_data.get('seller'),
        "salesorder_number": get_next_test_number(),
        "date": form_data.get('contract_date'),
        "shipment_date": form_data.get('shipping_date'),
        "notes": form_data.get('delivery_notes'),
        "terms": form_data.get('terms'),
        "location_id": form_data.get('location_id'),
        "line_items": [
            {
                "item_id": form_data.get('commodity'),
                "quantity": form_data.get('quantity', 1),
                "rate": form_data.get('commission_rate'),
            }
        ],
        "custom_fields": [
            {"api_name": "cf_buyer", "value": form_data.get('buyer_name')},
            {"api_name": "cf_item_contract_price", "value": form_data.get('commodity_rate')},
            {"api_name": "cf_vessel_name", "value": form_data.get('vessel_name')},
            {"api_name": "cf_trnspname", "value": form_data.get('transportation')},
            {"api_name": "cf_uom", "value": form_data.get('uom')},
            {"api_name": "cf_customer_ref", "value": form_data.get('seller_reference')},
            {"api_name": "cf_co_broker", "value": form_data.get('co_broker_name')},
            {"api_name": "cf_co_brokerage_rate", "value": form_data.get('co_brokerage_rate')},
        ],
        "salesperson_id": form_data.get('salesperson_employee_id', ''),
    }

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

    payload = {
        "customer_id": form_data.get('seller'),
        "date": form_data.get('contract_date'),
        "shipment_date": form_data.get('shipping_date'),
        "notes": form_data.get('delivery_notes'),
        "terms": form_data.get('terms'),
        "line_items": [
            {
                "item_id": form_data.get('commodity'),
                "quantity": form_data.get('quantity'),
                "rate": form_data.get('commission_rate'),
            }
        ],
        "custom_fields": [
            {"api_name": "cf_buyer", "value": form_data.get('buyer_name')},
            {"api_name": "cf_item_contract_price", "value": form_data.get('commodity_rate')},
            {"api_name": "cf_vessel_name", "value": form_data.get('vessel_name')},
            {"api_name": "cf_trnspname", "value": form_data.get('transportation')},
            {"api_name": "cf_uom", "value": form_data.get('uom')},
            {"api_name": "cf_customer_ref", "value": form_data.get('seller_reference')},
            {"api_name": "cf_co_broker", "value": form_data.get('co_broker_name')},
            {"api_name": "cf_co_brokerage_rate", "value": form_data.get('co_brokerage_rate')},
            # TODO: confirm api_name for shipping end date once known
            {"api_name": "cf_shipping_date_end", "value": form_data.get('shipping_date_end')},
        ],
        "salesperson_id": form_data.get('salesperson_employee_id', ''),
    }

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
    }


if __name__ == '__main__':
    token = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": ORG_ID, "per_page": 1}
    )
    print(response.json())