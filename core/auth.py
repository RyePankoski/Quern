"""
MSAL / Azure AD authentication helpers.
Quern uses Azure AD only as a gatekeeper — once a Microsoft account is verified,
the user must exist in Quern's local users table (by email) to be allowed in.
"""
import os
import msal
from flask import url_for, session

CLIENT_ID = os.getenv('AZURE_CLIENT_ID')
CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET')
TENANT_ID = os.getenv('AZURE_TENANT_ID')

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}" if TENANT_ID else None
SCOPES = ['User.Read']  # Microsoft Graph delegated; gets us preferred_username


def _build_msal_app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
    )


def _redirect_uri():
    return os.getenv('AZURE_REDIRECT_URI') or url_for('auth_callback', _external=True)


def build_auth_url():
    app = _build_msal_app()
    flow = app.initiate_auth_code_flow(
        SCOPES,
        redirect_uri=_redirect_uri(),
    )
    session['auth_flow'] = flow
    return flow['auth_uri']


def acquire_token_by_code(request_args):
    app = _build_msal_app()
    return app.acquire_token_by_auth_code_flow(
        session.pop('auth_flow', {}),
        request_args,
    )
