"""
Inventory Module.

This module handles all product-related operations:
- Product Families (5-digit ECWID groupings)
- Product Identities (Layer 1: Engineering)
- Product Variants (Layer 2: Sales)
- Bundle Components (Bill of Materials)
- Platform Listings (External sync)
- Inventory Items (Physical tracking)
"""
from app.modules.inventory import routes, schemas

__all__ = ["routes", "schemas"]

