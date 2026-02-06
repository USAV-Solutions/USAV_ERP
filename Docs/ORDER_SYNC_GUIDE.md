# Order Synchronization Setup Guide

## Overview
The order synchronization system allows you to automatically import orders from multiple e-commerce platforms (eBay, Ecwid) into your inventory management system.

## Supported Platforms

### 1. eBay (3 Stores)
- **eBay Mekong** - Platform code: `EBAY_MEKONG`
- **eBay USAV** - Platform code: `EBAY_USAV`
- **eBay Dragon** - Platform code: `EBAY_DRAGON`

### 2. Ecwid
- Platform code: `ECWID`

### 3. Walmart (Coming Soon)
- Platform code: `WALMART`

## Configuration

### Environment Variables

Copy the `.env.example` file to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

### eBay Configuration

eBay uses OAuth 2.0 with refresh tokens. All three stores share the same App ID and Cert ID but have different refresh tokens.

```env
# Shared eBay credentials
EBAY_APP_ID=your-ebay-app-id
EBAY_CERT_ID=your-ebay-cert-id
EBAY_RU_NAME=your-ebay-ru-name
EBAY_SANDBOX=false

# Store-specific refresh tokens
EBAY_REFRESH_TOKEN_MEKONG=your-mekong-refresh-token
EBAY_REFRESH_TOKEN_USAV=your-usav-refresh-token
EBAY_REFRESH_TOKEN_DRAGON=your-dragon-refresh-token
```

#### Getting eBay Credentials:

1. **App ID & Cert ID**:
   - Go to [eBay Developer Program](https://developer.ebay.com/)
   - Create an application
   - Get your App ID (Client ID) and Cert ID (Client Secret)

2. **Refresh Tokens**:
   - Use eBay's OAuth consent flow to obtain user tokens
   - Exchange authorization code for refresh token
   - Store refresh tokens securely (they don't expire unless revoked)

3. **RU Name**:
   - Set up a redirect URI in your eBay application settings
   - Use the RU Name provided by eBay

### Ecwid Configuration

Ecwid uses a simple store ID and secret token (API access token).

```env
ECWID_STORE_ID=your-store-id
ECWID_SECRET=your-secret-access-token
```

#### Getting Ecwid Credentials:

1. Log in to your Ecwid admin panel
2. Go to **Settings → API**
3. Create a new API token with the following permissions:
   - Read orders
   - Update products (for inventory sync)
4. Copy your Store ID and Secret Token

### Walmart Configuration (Future)

```env
WALMART_CLIENT_ID=your-walmart-client-id
WALMART_CLIENT_SECRET=your-walmart-client-secret
```

## Using the Order Sync Feature

### Via Web Interface

1. **Navigate to Orders Page**:
   - Log in to the application
   - Click on **Orders** in the sidebar

2. **Sync Orders**:
   - Click the **"Sync Orders"** button in the top right
   - Select a platform (eBay Mekong, eBay USAV, eBay Dragon, or Ecwid)
   - Choose a date (defaults to today)
   - Click **"Sync Orders"**

3. **View Results**:
   - The system will show how many orders were fetched
   - New orders vs. existing orders
   - Any errors that occurred

### Via API

#### Sync Today's Orders

```bash
POST /api/v1/orders/sync/ECWID
POST /api/v1/orders/sync/EBAY_USAV
POST /api/v1/orders/sync/EBAY_MEKONG
POST /api/v1/orders/sync/EBAY_DRAGON
```

#### Sync Specific Date

```bash
POST /api/v1/orders/sync/ECWID?order_date=2026-02-05
POST /api/v1/orders/sync/EBAY_USAV?order_date=2026-02-05
```

#### Response Format

```json
{
  "success": true,
  "platform": "ECWID",
  "date": "2026-02-06",
  "total_fetched": 15,
  "new_orders": 12,
  "existing_orders": 3,
  "errors": 0
}
```

## Order Processing Workflow

### 1. Order Import
When orders are synced, they are automatically:
- Saved to the database
- Assigned a platform identifier
- Given a PENDING status

### 2. SKU Matching (Automatic)
The system attempts to match order items to internal SKUs using:
1. **ASIN matching** (for Amazon orders)
2. **Platform listing ID** (eBay Item ID, Ecwid Product ID)
3. **SKU matching** (direct SKU comparison)

Successfully matched items move to **MATCHED** status.

### 3. Manual Matching
Orders with unmatched items remain in PENDING status and require manual intervention:
- Navigate to the order details
- Match unmatched items to the correct SKU
- Once all items are matched, order moves to PROCESSING

### 4. Inventory Allocation
After matching, warehouse staff can:
- Allocate specific inventory items to order items
- Status changes to ALLOCATED when complete

### 5. Shipping
When ready to ship:
- Mark order as READY_TO_SHIP
- Process shipment
- Update tracking information
- Mark as SHIPPED

## Troubleshooting

### "Platform not configured" Error
- Check that all required environment variables are set
- Verify credentials are correct
- Restart the backend after updating .env

### OAuth Errors (eBay)
- Refresh tokens may have expired or been revoked
- Regenerate refresh tokens through eBay OAuth flow
- Check that scopes include:
  - `https://api.ebay.com/oauth/api_scope`
  - `https://api.ebay.com/oauth/api_scope/sell.fulfillment`
  - `https://api.ebay.com/oauth/api_scope/sell.inventory`

### No Orders Fetched
- Verify the date range has orders on the platform
- Check API credentials have proper permissions
- Review backend logs for detailed error messages

### Duplicate Orders
- The system automatically skips orders that already exist
- Duplicate detection uses platform + external_order_id

## API Rate Limits

### eBay
- Fulfillment API: 5,000 calls per day per application
- Rate limit: Typically 5 requests per second

### Ecwid
- API calls: 500 per 5 minutes per store
- Higher limits available on paid plans

### Walmart
- Varies by endpoint and partnership tier

## Best Practices

1. **Schedule Regular Syncs**:
   - Run daily syncs for each platform
   - Consider morning sync for overnight orders

2. **Monitor Unmatched Items**:
   - Check unmatched items dashboard daily
   - Create SKU mappings for frequently unmatched products

3. **Backup Before Bulk Operations**:
   - Database backups before large imports
   - Test sync with small date ranges first

4. **Token Management**:
   - Store tokens securely in environment variables
   - Rotate tokens periodically
   - Monitor for token expiration

## Support

For issues or questions:
- Check application logs: `docker compose logs backend-dev`
- Review API endpoint documentation: `http://localhost:8080/docs`
- Contact system administrator

## Future Enhancements

- Automated daily sync scheduling
- Webhook support for real-time order updates
- Amazon integration
- Walmart integration
- Multi-warehouse allocation
- Shipping label generation
- Return order handling
