"""
FBA order import module.

Server-side port of the local ``FBA/`` pipeline. Ingests the two raw Amazon
Seller Central exports (All-Orders ``.txt`` + Amazon-Fulfilled-Shipments
``.csv``), merges them, scrapes any missing buyer names from Seller Central with
a persistent Chromium profile, and feeds the result through the existing
``AMAZON_FBA_CSV`` order ingestion.

See ``Docs/FBA_Import_Handoff.md``.
"""
