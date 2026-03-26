import requests
import os
from dotenv import load_dotenv
from models import db, Customer, Item, Employee
from datetime import datetime

import time
import json
import os

load_dotenv()

CLIENT_ID = os.getenv('ZOHO_CLIENT_ID')
CLIENT_SECRET = os.getenv('ZOHO_CLIENT_SECRET')
REFRESH_TOKEN = os.getenv('ZOHO_REFRESH_TOKEN')
ORG_ID = os.getenv('ZOHO_ORG_ID')

_token_cache = {"access_token": None, "expires_at": 0}

_TOKEN_FILE = ".token_cache"


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


def get_access_token():
    if os.path.exists(_TOKEN_FILE):
        with open(_TOKEN_FILE) as f:
            cache = json.load(f)
        if time.time() < cache.get("expires_at", 0):
            return cache["access_token"]

    response = requests.post(
        "https://accounts.zoho.com/oauth/v2/token",
        params={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": REFRESH_TOKEN,
        }
    )
    data = response.json()
    if 'access_token' not in data:
        raise RuntimeError(f"Failed to get access token: {data}")

    cache = {
        "access_token": data["access_token"],
        "expires_at": time.time() + 3500
    }
    with open(_TOKEN_FILE, "w") as f:
        json.dump(cache, f)

    return data["access_token"]


def get_sales_orders(page=1):
    coin = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {coin}"},
        params={"organization_id": ORG_ID, "per_page": 200, "page": page}
    )
    return response.json().get('salesorders', [])


def sync_customers():
    token = get_access_token()
    page = 1

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
            existing = Customer.query.get(contact['contact_id'])
            if existing:
                existing.customer_name = contact['contact_name']
            else:
                new_customer = Customer(
                    customer_id=contact['contact_id'],
                    customer_name=contact['contact_name']
                )
                db.session.add(new_customer)

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
        else:
            new_item = Item(
                item_id=item['id'],
                item_name=item['name']
            )
            db.session.add(new_item)
    db.session.commit()


# def get_access_token():
#     import time
#     if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
#         return _token_cache["access_token"]
#
#     response = requests.post(
#         "https://accounts.zoho.com/oauth/v2/token",
#         params={
#             "grant_type": "refresh_token",
#             "client_id": CLIENT_ID,
#             "client_secret": CLIENT_SECRET,
#             "refresh_token": REFRESH_TOKEN,
#         }
#     )
#     data = response.json()
#     if 'access_token' not in data:
#         raise RuntimeError(f"Failed to get access token: {data}")
#
#     _token_cache["access_token"] = data["access_token"]
#     _token_cache["expires_at"] = time.time() + 3500
#     return data["access_token"]


def get_items():
    coin = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/items",
        headers={"Authorization": f"Zoho-oauthtoken {coin}"},
        params={"organization_id": ORG_ID, "contact_type": "customer", "per_page": 200}
    )
    items = response.json().get('items', [])
    return [{"id": item["item_id"], "name": item["item_name"]} for item in items]


def get_customers():
    coin = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/contacts",
        headers={"Authorization": f"Zoho-oauthtoken {coin}"},
        params={"organization_id": ORG_ID, "contact_type": "customer", "per_page": 200}
    )
    contacts = response.json().get('contacts', [])
    return [{"id": contact["contact_id"], "name": contact["contact_name"]} for contact in contacts]


def submit_contract(form_data):
    coin = get_access_token()

    payload = {
        "customer_id": form_data.get('seller'),
        "salesorder_number": get_next_test_number(),
        "date": form_data.get('contract_date'),
        "shipment_date": form_data.get('shipping_date'),
        "notes": form_data.get('delivery_notes'),
        "terms": form_data.get('terms'),
        "line_items": [
            {
                "item_id": form_data.get('commodity'),
                "quantity": form_data.get('quantity', 1),
                "rate": form_data.get('commission_rate'),
            }
        ],
        "custom_fields": [
            {"api_name": "cf_buyer", "value": form_data.get('buyer')},
            {"api_name": "cf_item_contract_price", "value": form_data.get('commodity_rate')},
            {"api_name": "cf_vessel_name", "value": form_data.get('vessel_name')},
            {"api_name": "cf_trnspname", "value": form_data.get('transportation')},
            {"api_name": "cf_uom", "value": form_data.get('uom')},
            {"api_name": "cf_customer_ref", "value": form_data.get('seller_reference')},
            {"api_name": "cf_co_broker", "value": form_data.get('co_broker_name')},
            {"api_name": "cf_co_brokerage_rate", "value": form_data.get('co_brokerage_rate')},
        ]
    }

    response = requests.post(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {coin}"},
        params={"organization_id": ORG_ID},
        json=payload
    )

    print(response.json())
    return response.json()


def get_sales_order(salesorder_id):
    token = get_access_token()
    response = requests.get(
        f"https://www.zohoapis.com/books/v3/salesorders/{salesorder_id}",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": ORG_ID}
    )
    return response.json().get('salesorder', {})


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
            {"api_name": "cf_buyer", "value": form_data.get('buyer')},
            {"api_name": "cf_item_contract_price", "value": form_data.get('commodity_rate')},
            {"api_name": "cf_vessel_name", "value": form_data.get('vessel_name')},
            {"api_name": "cf_trnspname", "value": form_data.get('transportation')},
            {"api_name": "cf_uom", "value": form_data.get('uom')},
            {"api_name": "cf_customer_ref", "value": form_data.get('seller_reference')},
            {"api_name": "cf_co_broker", "value": form_data.get('co_broker_name')},
            {"api_name": "cf_co_brokerage_rate", "value": form_data.get('co_brokerage_rate')},
        ]
    }

    response = requests.put(
        f"https://www.zohoapis.com/books/v3/salesorders/{salesorder_id}",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": ORG_ID},
        json=payload
    )

    print(response.json())
    return response.json()


if __name__ == '__main__':
    token = get_access_token()
    response = requests.get(
        "https://www.zohoapis.com/books/v3/salesorders",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"organization_id": ORG_ID, "per_page": 1}
    )
    print(response.json())
