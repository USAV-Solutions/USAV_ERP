from app.integrations.zoho.sync_engine import (
    customer_to_zoho_payload,
    zoho_contact_to_customer_fields,
)
from app.models.entities import Customer


def test_customer_to_zoho_payload_uses_amazon_buyer_id_for_contact_name():
    customer = Customer(
        name="Vernon",
        email="c9mkswq337y2gxm@marketplace.amazon.com",
        amazon_buyer_id="c9mkswq337y2gxm",
        source="AMAZON_FBA_CSV",
        is_active=True,
    )

    payload = customer_to_zoho_payload(customer)

    assert payload["contact_name"] == "Amazon FBA - c9mkswq337y2gxm"
    assert payload["contact_persons"][0]["first_name"] == "Vernon"


def test_zoho_contact_to_customer_fields_keeps_human_name_and_extracts_amazon_buyer_id():
    payload = {
        "contact_name": "Amazon FBA - c9mkswq337y2gxm",
        "first_name": "Vernon",
        "email": "c9mkswq337y2gxm@marketplace.amazon.com",
    }

    fields = zoho_contact_to_customer_fields(payload)

    assert fields["amazon_buyer_id"] == "c9mkswq337y2gxm"
    assert fields["name"] == "Vernon"
    assert fields["email"] == "c9mkswq337y2gxm@marketplace.amazon.com"
