import os

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, redirect, request, session, jsonify
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from quickbooks import QuickBooks
from quickbooks.objects.company_info import CompanyInfo

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]

auth_client = AuthClient(
    client_id=os.environ["QBO_CLIENT_ID"],
    client_secret=os.environ["QBO_CLIENT_SECRET"],
    redirect_uri=os.environ["QBO_REDIRECT_URI"],
    environment=os.environ["QBO_ENVIRONMENT"],
)


def get_qb_client():
    return QuickBooks(
        auth_client=auth_client,
        refresh_token=session["refresh_token"],
        company_id=session["realm_id"],
    )


def trial_balance_to_dataframe(report):
    columns = [col["ColTitle"] or "Account" for col in report["Columns"]["Column"]]

    rows = []

    def walk(row_list):
        for row in row_list:
            if "ColData" in row:
                rows.append([col.get("value", "") for col in row["ColData"]])
            if "Rows" in row:
                walk(row["Rows"].get("Row", []))

    walk(report["Rows"].get("Row", []))

    return pd.DataFrame(rows, columns=columns)


@app.route("/")
def index():
    if "refresh_token" in session:
        return (
            '<a href="/company-info">View sandbox company info</a> | '
            '<a href="/trial-balance">View trial balance</a> | '
            '<a href="/disconnect">Disconnect</a>'
        )
    auth_url = auth_client.get_authorization_url([Scopes.ACCOUNTING])
    return f'<a href="{auth_url}">Connect to QuickBooks Sandbox</a>'


@app.route("/callback")
def callback():
    auth_code = request.args.get("code")
    realm_id = request.args.get("realmId")

    auth_client.get_bearer_token(auth_code, realm_id=realm_id)

    session["refresh_token"] = auth_client.refresh_token
    session["realm_id"] = realm_id

    return redirect("/")


@app.route("/company-info")
def company_info():
    client = get_qb_client()
    company = CompanyInfo.get(1, qb=client)
    return jsonify(company.to_dict())


@app.route("/trial-balance")
def trial_balance():
    client = get_qb_client()
    report = client.get_report("TrialBalance")

    df = trial_balance_to_dataframe(report)

    print("\nTrial Balance (from QuickBooks Sandbox):", flush=True)
    print(df.to_string(index=False), flush=True)

    return df.to_html(index=False)


@app.route("/disconnect")
def disconnect():
    session.clear()
    return redirect("/")


if __name__ == "__main__":
    app.run(port=8000, debug=True)
