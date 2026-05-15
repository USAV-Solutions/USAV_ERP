from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import ConditionCode, IdentityType
from app.modules.inventory.routes.variants import (
    _condition_code_value,
    _validate_convert_to_kit_children,
)


def _build_variant(variant_id: int, identity_id: int, identity_type: IdentityType):
    return SimpleNamespace(
        id=variant_id,
        identity_id=identity_id,
        identity=SimpleNamespace(
            id=identity_id,
            type=identity_type,
            generated_upis_h=f"ID-{identity_id}",
        ),
    )


def _build_child_line(child_variant_id: int, quantity_required: int = 1, role: str = "Primary"):
    return SimpleNamespace(
        child_variant_id=child_variant_id,
        quantity_required=quantity_required,
        role=role,
    )


def test_condition_code_value_handles_none_enum_and_raw_string():
    assert _condition_code_value(None) is None
    assert _condition_code_value(ConditionCode.N) == "N"
    assert _condition_code_value("U") == "U"


def test_validate_convert_to_kit_children_happy_path():
    children = [
        _build_child_line(101, quantity_required=2, role="Primary"),
        _build_child_line(102, quantity_required=1, role="Accessory"),
    ]
    child_variants = {
        101: _build_variant(101, 201, IdentityType.PRODUCT),
        102: _build_variant(102, 202, IdentityType.P),
    }

    resolved = _validate_convert_to_kit_children(
        source_variant_id=10,
        source_identity_id=110,
        children=children,
        child_variants_by_id=child_variants,
    )

    assert len(resolved) == 2
    assert resolved[0][0].id == 101
    assert resolved[0][1] == 2
    assert resolved[1][0].id == 102
    assert resolved[1][2] == "Accessory"


def test_validate_convert_to_kit_children_rejects_missing_or_inactive_child():
    children = [_build_child_line(999)]

    with pytest.raises(HTTPException) as exc_info:
        _validate_convert_to_kit_children(
            source_variant_id=10,
            source_identity_id=110,
            children=children,
            child_variants_by_id={},
        )

    assert exc_info.value.status_code == 404
    assert "not found or inactive" in str(exc_info.value.detail)


def test_validate_convert_to_kit_children_rejects_self_reference():
    children = [_build_child_line(10)]
    child_variants = {10: _build_variant(10, 110, IdentityType.PRODUCT)}

    with pytest.raises(HTTPException) as exc_info:
        _validate_convert_to_kit_children(
            source_variant_id=10,
            source_identity_id=110,
            children=children,
            child_variants_by_id=child_variants,
        )

    assert exc_info.value.status_code == 400
    assert "cannot reference the source product itself" in str(exc_info.value.detail)


def test_validate_convert_to_kit_children_rejects_bundle_or_kit_children():
    children = [_build_child_line(201)]
    child_variants = {201: _build_variant(201, 301, IdentityType.B)}

    with pytest.raises(HTTPException) as exc_info:
        _validate_convert_to_kit_children(
            source_variant_id=10,
            source_identity_id=110,
            children=children,
            child_variants_by_id=child_variants,
        )

    assert exc_info.value.status_code == 400
    assert "not allowed for kit children" in str(exc_info.value.detail)


def test_validate_convert_to_kit_children_rejects_duplicate_child_identity():
    children = [_build_child_line(301), _build_child_line(302)]
    child_variants = {
        301: _build_variant(301, 401, IdentityType.PRODUCT),
        302: _build_variant(302, 401, IdentityType.P),
    }

    with pytest.raises(HTTPException) as exc_info:
        _validate_convert_to_kit_children(
            source_variant_id=10,
            source_identity_id=110,
            children=children,
            child_variants_by_id=child_variants,
        )

    assert exc_info.value.status_code == 400
    assert "Duplicate child identity" in str(exc_info.value.detail)
