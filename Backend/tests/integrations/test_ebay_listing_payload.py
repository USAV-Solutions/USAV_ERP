from app.integrations.ebay.client import EbayClient


def _client() -> EbayClient:
    return EbayClient(store_name="USAV", app_id="x", cert_id="y", refresh_token="z", sandbox=True)


def test_condition_id_mapping():
    client = _client()
    assert client.to_condition_id("NEW") == 1000
    assert client.to_condition_id("U") == 3000
    assert client.to_condition_id("for parts") == 7000
    assert client.to_condition_id("mystery") is None


def test_item_specifics_mapping():
    client = _client()
    specifics = client.to_item_specifics(
        brand="Acme",
        mpn="MPN-123",
        color="Black",
        upc="123456789012",
        extra_specifics=[{"name": "Material", "value": "Steel"}],
    )
    assert {entry["Name"] for entry in specifics} == {"Brand", "MPN", "Color", "UPC", "Material"}


def test_shipping_package_details_mapping():
    client = _client()
    details = client.to_shipping_package_details(
        weight_lbs=2.5,
        length_in=10.0,
        width_in=5.0,
        height_in=3.0,
    )
    assert details is not None
    assert details["WeightMajor"] == "2"
    assert details["WeightMinor"] == "8"
    assert details["PackageLength"] == "10.00"


def test_add_fixed_price_item_xml_contains_required_fields_and_cdata():
    client = _client()
    payload = {
        "title": "Test <Title>",
        "description": "<p>Hello</p>",
        "category_id": "1234",
        "price": 19.99,
        "quantity": 2,
        "condition_id": 1000,
        "country": "US",
        "currency": "USD",
        "dispatch_time_max": 1,
        "location": "Texas",
        "postal_code": "75001",
        "sku": "SKU-1",
        "picture_urls": ["https://example.com/image.jpg"],
        "item_specifics": [{"Name": "Brand", "Value": ["Acme"]}],
        "shipping_package_details": {
            "WeightMajor": "1",
            "WeightMinor": "0",
            "PackageLength": "10.00",
            "PackageWidth": "4.00",
            "PackageDepth": "2.00",
        },
        "payment_profile_id": "111",
        "return_profile_id": "222",
        "shipping_profile_id": "333",
    }
    xml_payload = client.build_add_fixed_price_item_xml(payload)
    assert "<DispatchTimeMax>1</DispatchTimeMax>" in xml_payload
    assert "<ListingDuration>GTC</ListingDuration>" in xml_payload
    assert "<PrimaryCategory>" in xml_payload
    assert "<CategoryID>1234</CategoryID>" in xml_payload
    assert "<![CDATA[<p>Hello</p>]]>" in xml_payload
    assert "<PictureDetails><PictureURL>https://example.com/image.jpg</PictureURL></PictureDetails>" in xml_payload
    assert "<SellerProfiles>" in xml_payload
