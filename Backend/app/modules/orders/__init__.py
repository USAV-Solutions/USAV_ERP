"""
Orders Module.

This module handles order synchronization and SKU resolution:
- Order ingestion from external platforms (Amazon, eBay, Ecwid)
- Integration state tracking (sync heartbeat)
- Auto-matching external items to internal product variants
- Manual SKU resolution ("Match & Learn")
"""
