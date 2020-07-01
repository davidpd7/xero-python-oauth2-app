# -*- coding: utf-8 -*-
import os
import time
from pathlib import Path
from random import seed
from random import randint
from functools import wraps
from io import BytesIO
from logging.config import dictConfig

from flask import Flask, url_for, render_template, session, redirect, json, send_file
from flask_oauthlib.contrib.client import OAuth, OAuth2Application
from flask_session import Session
from xero_python.accounting import AccountingApi, ContactPerson, Contact, Contacts, Account, Accounts, AccountType
from xero_python.api_client import ApiClient, serialize
from xero_python.api_client.configuration import Configuration
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.exceptions import AccountingBadRequestException
from xero_python.identity import IdentityApi
from xero_python.utils import getvalue

import logging_settings
from utils import jsonify, serialize_model

dictConfig(logging_settings.default_settings)

# configure main flask application
app = Flask(__name__)
app.config.from_object("default_settings")
app.config.from_pyfile("config.py", silent=True)

if app.config["ENV"] != "production":
    # allow oauth2 loop to run over http (used for local testing only)
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# configure persistent session cache
Session(app)

# configure flask-oauthlib application
# TODO fetch config from https://identity.xero.com/.well-known/openid-configuration #1
oauth = OAuth(app)
xero = oauth.remote_app(
    name="xero",
    version="2",
    client_id=app.config["CLIENT_ID"],
    client_secret=app.config["CLIENT_SECRET"],
    endpoint_url="https://api.xero.com/",
    authorization_url="https://login.xero.com/identity/connect/authorize",
    access_token_url="https://identity.xero.com/connect/token",
    refresh_token_url="https://identity.xero.com/connect/token",
    scope="offline_access openid profile email accounting.transactions "
    "accounting.transactions.read accounting.reports.read "
    "accounting.journals.read accounting.settings accounting.settings.read "
    "accounting.contacts accounting.contacts.read accounting.attachments "
    "accounting.attachments.read assets projects",
)  # type: OAuth2Application


# configure xero-python sdk client
api_client = ApiClient(
    Configuration(
        debug=app.config["DEBUG"],
        oauth2_token=OAuth2Token(
            client_id=app.config["CLIENT_ID"], client_secret=app.config["CLIENT_SECRET"]
        ),
    ),
    pool_threads=1,
)


# configure token persistence and exchange point between flask-oauthlib and xero-python
@xero.tokengetter
@api_client.oauth2_token_getter
def obtain_xero_oauth2_token():
    return session.get("token")


@xero.tokensaver
@api_client.oauth2_token_saver
def store_xero_oauth2_token(token):
    session["token"] = token
    session.modified = True


def xero_token_required(function):
    @wraps(function)
    def decorator(*args, **kwargs):
        xero_token = obtain_xero_oauth2_token()
        if not xero_token:
            return redirect(url_for("login", _external=True))

        return function(*args, **kwargs)

    return decorator

def attachment_image():
    return Path(__file__).resolve().parent.joinpath("helo-heros.jpg")


@app.route("/")
def index():
    xero_access = dict(obtain_xero_oauth2_token() or {})
    return render_template(
        "code.html",
        title="Home | oauth token",
        code=json.dumps(xero_access, sort_keys=True, indent=4),
    )


@app.route("/tenants")
@xero_token_required
def tenants():
    identity_api = IdentityApi(api_client)
    accounting_api = AccountingApi(api_client)

    available_tenants = []
    for connection in identity_api.get_connections():
        tenant = serialize(connection)
        if connection.tenant_type == "ORGANISATION":
            organisations = accounting_api.get_organisations(
                xero_tenant_id=connection.tenant_id
            )
            tenant["organisations"] = serialize(organisations)

        available_tenants.append(tenant)

    return render_template(
        "code.html",
        title="Xero Tenants",
        code=json.dumps(available_tenants, sort_keys=True, indent=4),
    )


@app.route("/create-contact-person")
@xero_token_required
def create_contact_person():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact_person = ContactPerson(
        first_name="John",
        last_name="Smith",
        email_address="john.smith@24locks.com",
        include_in_emails=True,
    )
    contact = Contact(
        name="FooBar",
        first_name="Foo",
        last_name="Bar",
        email_address="ben.bowden@24locks.com",
        contact_persons=[contact_person],
    )
    contacts = Contacts(contacts=[contact])
    try:
        created_contacts = accounting_api.create_contacts(
            xero_tenant_id, contacts=contacts
        )  # type: Contacts
    except AccountingBadRequestException as exception:
        sub_title = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        sub_title = "Contact {} created.".format(
            getvalue(created_contacts, "contacts.0.name", "")
        )
        code = serialize_model(created_contacts)

    return render_template(
        "code.html", title="Create Contacts", code=code, sub_title=sub_title
    )


@app.route("/accounts")
@xero_token_required
def accounts():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + randNum,
        code=randNum,
        description="My Foobar",
        type=AccountType.EXPENSE,
    )
    accounts = Accounts(accounts=[account])
    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account=account
        )  # type: Accounts
        account_id = getvalue(created_accounts, "accounts.0.account_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Account {} created.".format(
            getvalue(created_accounts, "accounts.0.name", "")
        )
        msgs['value'].append(msg)

    # UPDATE ACCOUNT
    accountUp = Account(
        description="Update me",
    )
    accountsUp = Accounts(accounts=[accountUp])
    try:
        created_accounts = accounting_api.update_account(
            xero_tenant_id, account_id, accountsUp
        )  # type: Accounts
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Account description '{}' updated.".format(
            getvalue(created_accounts, "accounts.0.description", "")
        )
        msgs['value'].append(msg)
    
    # CREATE ACCOUNT ATTACHMENT
    
    # READ ALL ACCOUNTS
    try:
        where = "Status==\"ACTIVE\"";
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id,
            where=where
        )  # type: Accounts
        attachment_account_id = getvalue(created_accounts, "accounts.0.account_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        try: 
            include_online = True
            myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
            with myimage.open("rb") as image:
                account_attachment_created = accounting_api.create_account_attachment_by_file_name(
                    xero_tenant_id,
                    attachment_account_id,
                    file_name=myimage.name,
                    body=image.read(),
                )  # type: Attachments
        except AccountingBadRequestException as exception:
            msg = "Error: " + exception.reason
            code = jsonify(exception.error_data)
        else:
            msg = "Attachment url '{}' created.".format(
                getvalue(account_attachment_created, "account_attachment.0.url", "")
            )
            msgs['value'].append(msg)
    
    # ARCHIVE ACCOUNT
    accountUp = Account(
        status="ARCHIVED",
    )
    accountsUp = Accounts(accounts=[accountUp])
    try:
        created_accounts = accounting_api.update_account(
            xero_tenant_id, account_id, accountsUp
        )  # type: Accounts
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Account status '{}' archived.".format(
            getvalue(created_accounts, "accounts.0.status", "")
        )
        msgs['value'].append(msg)
    
    # READ ALL ACCOUNTS
    try:
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id
        )  # type: Accounts
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Accounts Total {} read.".format(
            len(read_accounts.accounts)
        )
        msgs['value'].append(msg)
    
    # READ SINGLE ACCOUNT
    try:
        read_one_account = accounting_api.get_account(
            xero_tenant_id, account_id
        )  # type: Accounts
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Account {} read.".format(
            getvalue(read_accounts, "accounts.0.name", "")
        )
        #code = serialize_model(read_accounts)
        msgs['value'].append(msg)
        
    # DELETE ACCOUNT
    try:
        created_accounts = accounting_api.delete_account(
            xero_tenant_id, account_id
        )  # type: Accounts
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Account deleted."
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )


@app.route("/create-multiple-contacts")
@xero_token_required
def create_multiple_contacts():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact = Contact(
        name="George Jetson",
        first_name="George",
        last_name="Jetson",
        email_address="george.jetson@aol.com",
    )
    # Add the same contact twice - the first one will succeed, but the
    # second contact will fail with a validation error which we'll show.
    contacts = Contacts(contacts=[contact, contact])
    try:
        created_contacts = accounting_api.create_contacts(
            xero_tenant_id, contacts=contacts, summarize_errors=False
        )  # type: Contacts
    except AccountingBadRequestException as exception:
        sub_title = "Error: " + exception.reason
        result_list = None
        code = jsonify(exception.error_data)
    else:
        sub_title = ""
        result_list = []
        for contact in created_contacts.contacts:
            if contact.has_validation_errors:
                error = getvalue(contact.validation_errors, "0.message", "")
                result_list.append("Error: {}".format(error))
            else:
                result_list.append("Contact {} created.".format(contact.name))

        code = serialize_model(created_contacts)

    return render_template(
        "code.html",
        title="Create Multiple Contacts",
        code=code,
        result_list=result_list,
        sub_title=sub_title,
    )


@app.route("/invoices")
@xero_token_required
def get_invoices():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    invoices = accounting_api.get_invoices(
        xero_tenant_id, statuses=["DRAFT", "SUBMITTED"]
    )
    code = serialize_model(invoices)
    sub_title = "Total invoices found: {}".format(len(invoices.invoices))

    return render_template(
        "code.html", title="Invoices", code=code, sub_title=sub_title
    )


@app.route("/login")
def login():
    redirect_url = url_for("oauth_callback", _external=True)
    response = xero.authorize(callback_uri=redirect_url)
    return response


@app.route("/callback")
def oauth_callback():
    try:
        response = xero.authorized_response()
    except Exception as e:
        print(e)
        raise
    # todo validate state value
    if response is None or response.get("access_token") is None:
        return "Access denied: response=%s" % response
    store_xero_oauth2_token(response)
    return redirect(url_for("index", _external=True))


@app.route("/logout")
def logout():
    store_xero_oauth2_token(None)
    return redirect(url_for("index", _external=True))


@app.route("/export-token")
@xero_token_required
def export_token():
    token = obtain_xero_oauth2_token()
    buffer = BytesIO("token={!r}".format(token).encode("utf-8"))
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="x.python",
        as_attachment=True,
        attachment_filename="oauth2_token.py",
    )


@app.route("/refresh-token")
@xero_token_required
def refresh_token():
    xero_token = obtain_xero_oauth2_token()
    new_token = api_client.refresh_oauth2_token()
    return render_template(
        "code.html",
        title="Xero OAuth2 token",
        code=jsonify({"Old Token": xero_token, "New token": new_token}),
        sub_title="token refreshed",
    )


def get_xero_tenant_id():
    token = obtain_xero_oauth2_token()
    if not token:
        return None

    identity_api = IdentityApi(api_client)
    for connection in identity_api.get_connections():
        if connection.tenant_type == "ORGANISATION":
            return connection.tenant_id


if __name__ == "__main__":
    app.run()