"""
Tracking module.

Server-side, manually-triggered scraping of parcelsapp.com to refresh the
``shipping_status`` of eligible sales orders, with rate-limit-aware pausing.

See ``Backend/.context/tree/Backend/app/modules/tracking/README.md``.
"""
