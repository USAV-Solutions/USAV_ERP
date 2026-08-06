# Create eBay Listing Walkthrough

We've successfully adapted the eBay listing flow from `ebay-listing-helper` into the main `USAV_Inventory` application.

## What Was Done

### 1. Backend API Layer (`Backend/app/modules/inventory/routes/listings.py`)
- **eBay Accounts Configuration:** Added `GET /listings/ebay/accounts` to fetch store configuration details directly from `ebay-accounts.json` so you can choose which store to list on.
- **Category Taxonomy:** Added endpoints to query eBay categories (`GET /listings/ebay/categories`), category aspects (`GET /listings/ebay/categories/{category_id}/aspects`), and conditions (`GET /listings/ebay/categories/{category_id}/conditions`) through the USAV eBay API client.
- **AI Integrations:** Created endpoints using `google-genai` for:
  - `POST /listings/ebay/ai/shorten-title`: Condenses the title to under 80 characters.
  - `POST /listings/ebay/ai/generate-description`: Generates professional HTML descriptions from item specifics and titles.
  - `POST /listings/ebay/ai/suggest-details`: Uses eBay's Draft/Preview APIs and Gemini to suggest categories, specs, and estimated dimensions.
- **Publish Endpoint:** Added `POST /listings/ebay/publish` which takes the payload, creates an Inventory Item and Offer via eBay's Inventory API, publishes the offer, and records the listing reference and metadata to the database via `PlatformListingRepository`.

### 2. Frontend React Application (`frontend/src/`)
- **API and Types:** Created `ebayListing.ts` in both `api` and `types` folders to provide strong typing and clean HTTP calls.
- **UI Stepper Component:** Created `CreateEbayListing.tsx` which houses a 3-step listing process:
  - **Step 1: SKU Selection (`SkuSelectionStep.tsx`).** You search your database for a `ProductVariant`. It pulls up the image, condition, name, and checks if it already has eBay listings.
  - **Step 2: Listing Details (`ListingDetailsStep.tsx`).** Auto-fills weight and dimensions if available. Includes "AI Shorten", "AI Generate", and "AI Suggest All" buttons. A dynamic `ItemSpecificsEditor` allows full customization of aspects.
  - **Step 3: Preview & Images (`PreviewPublishStep.tsx`).** Summarizes the data, auto-pulls images associated with the SKU, lets you upload new ones, select the ones you want to push, and then "Publish to eBay".
- **Navigation:** Integrated into `App.tsx` and the left sidebar under `Catalog -> Product Listings -> Create New Listing`.

### 3. Documentation
- Updated `Backend/.context/tree/Backend/app/modules/inventory/routes/README.md` to reflect the new eBay listing endpoints and functionality in compliance with `AGENTS.md`.

## How to Verify

1. **Start the applications:** Ensure both the `Backend` and `frontend` are running.
2. **Configure API Keys:** Make sure the `Backend/.env` has `GEMINI_API_KEY` set so the AI features will work.
3. **Navigate to the UI:** Go to the application and open **Catalog > Product Listings**. You will see a new **Create New Listing** option.
4. **Test the Flow:**
   - **Step 1:** Search for an existing SKU.
   - **Step 2:** Click **AI Suggest All** to auto-assign a category and aspects. Try clicking **AI Shorten** and **AI Generate** to create the title and description.
   - **Step 3:** Select some images, review the summary, and click **Publish to eBay**. (Note: Depending on whether you're using sandbox or production eBay credentials, this will actually create a listing.)

## Outstanding Items
- **Saving Drafts:** The "Save Draft" button on the final step currently shows a success message but is a placeholder. If you need draft listings saved to the DB without publishing to eBay, we can implement a `DraftListing` model in the future.
- **AI Failures:** The system degrades gracefully; if you lack an API key, the AI buttons will surface a toast error, but you can still manually fill out the category, title, and description.

If you encounter any issues with the UI flow or eBay API configurations, let me know and we can refine them!