import pytest
from unittest.mock import MagicMock, patch

import app.models
from app.modules.orders.diagnose import diagnose_packaging_photo_bytes, AIDiagnosticResponse

@pytest.mark.asyncio
async def test_diagnose_empty_bytes():
    """Verify diagnose_packaging_photo_bytes handles empty payload correctly."""
    res = await diagnose_packaging_photo_bytes(image_bytes=b"")
    assert res.success is False
    assert res.status == "ERROR"
    assert "Empty image payload" in res.message

@pytest.mark.asyncio
async def test_diagnose_no_api_key(monkeypatch):
    """Verify diagnostic service returns clear error when API key is missing."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    res = await diagnose_packaging_photo_bytes(image_bytes=b"dummy image data")
    assert res.success is False
    assert res.status == "ERROR"
    assert "API key is not configured" in res.message

@pytest.mark.asyncio
async def test_diagnose_success(monkeypatch):
    """Verify diagnostic service invokes Gemini Vision AI and parses JSON result."""
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '''{
        "is_valid_packing_photo": true,
        "platform": "AMAZON",
        "order_id": "113-0602625-1537021",
        "tracking_number": "9300110990513442589502",
        "sku_on_slip": "AH-PL9M-F32Y",
        "detected_physical_item": "Coiled black 2-wire audio speaker cable",
        "confidence_score": 0.96
    }'''
    mock_client.models.generate_content.return_value = mock_response

    mock_genai = MagicMock()
    mock_genai.Client.return_value = mock_client
    monkeypatch.setitem(__import__('sys').modules, 'google', MagicMock(genai=mock_genai))
    monkeypatch.setitem(__import__('sys').modules, 'google.genai', mock_genai)
    monkeypatch.setitem(__import__('sys').modules, 'google.genai.types', MagicMock())

    res = await diagnose_packaging_photo_bytes(image_bytes=b"dummy image data")

    assert res.success is True
    assert res.is_valid_packing_photo is True
    assert res.platform == "AMAZON"
    assert res.order_id == "113-0602625-1537021"
    assert res.tracking_number == "9300110990513442589502"
    assert res.sku_on_slip == "AH-PL9M-F32Y"
    assert "speaker cable" in res.detected_physical_item.lower()
