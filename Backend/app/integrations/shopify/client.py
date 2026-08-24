"""
Shopify API Client.

Implements integration with Shopify platform for price synchronization.
"""
import asyncio
import logging
from typing import Optional, List

import httpx

logger = logging.getLogger(__name__)


class ShopifyClient:
    """
    Shopify Admin GraphQL API client for price synchronization.
    
    Requires:
    - shop_url: Your Shopify store URL (e.g., xxx.myshopify.com)
    - access_token: Shopify Admin API access token
    - api_version: API version to use (default: 2024-10)
    """
    
    def __init__(
        self,
        shop_url: str,
        access_token: str,
        api_version: str = "2024-10"
    ):
        self.shop_url = shop_url
        self.access_token = access_token
        self.api_version = api_version
        self.graphql_url = f"https://{shop_url}/admin/api/{api_version}/graphql.json"
        
        if not shop_url or not access_token:
            logger.warning("Shopify credentials not configured")

    def _get_headers(self) -> dict:
        return {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json"
        }

    async def _graphql(self, query: str, variables: Optional[dict] = None) -> dict:
        """
        Internal helper. Sends POST to GraphQL endpoint with query and variables. 
        Returns the JSON response. Handles rate limiting (if 429, sleep and retry). Logs errors.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                try:
                    payload = {"query": query}
                    if variables:
                        payload["variables"] = variables
                        
                    response = await client.post(
                        self.graphql_url,
                        headers=self._get_headers(),
                        json=payload
                    )
                    
                    if response.status_code == 429:
                        logger.warning("Shopify API rate limit hit, sleeping for 2 seconds...")
                        await asyncio.sleep(2.0)
                        continue
                        
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPError as e:
                    logger.error(f"Shopify GraphQL request failed: {e}")
                    raise

    async def test_connection(self) -> dict:
        """
        Query connection status.
        """
        query = "{ shop { name url myshopifyDomain } }"
        result = {
            "success": False,
            "authenticated": False,
            "store_info": None,
            "error": None
        }
        
        try:
            data = await self._graphql(query)
            if "data" in data and "shop" in data["data"]:
                result["success"] = True
                result["authenticated"] = True
                result["store_info"] = data["data"]["shop"]
                logger.info("Shopify connection test successful")
            elif "errors" in data:
                result["error"] = data["errors"]
                
        except Exception as e:
            result["error"] = f"Connection test failed: {str(e)}"
            logger.error(f"Shopify connection test failed: {e}")
            
        return result

    async def get_all_products(self) -> List[dict]:
        """
        Paginated GraphQL query to fetch ALL products with their variants.
        """
        query = """
        query getProducts($first: Int!, $cursor: String) {
          products(first: $first, after: $cursor) {
            pageInfo {
              hasNextPage
              endCursor
            }
            edges {
              node {
                id
                title
                handle
                variants(first: 100) {
                  edges {
                    node {
                      id
                      sku
                      price
                      compareAtPrice
                      title
                      inventoryQuantity
                    }
                  }
                }
              }
            }
          }
        }
        """
        
        all_variants = []
        cursor = None
        has_next_page = True
        
        while has_next_page:
            variables = {"first": 50, "cursor": cursor}
            data = await self._graphql(query, variables)
            
            # Simple rate limit to stay within budget
            await asyncio.sleep(0.5)
            
            if "errors" in data:
                logger.error(f"Error fetching products: {data['errors']}")
                break
                
            products_data = data.get("data", {}).get("products", {})
            page_info = products_data.get("pageInfo", {})
            edges = products_data.get("edges", [])
            
            for edge in edges:
                product_node = edge.get("node", {})
                product_id = product_node.get("id")
                product_title = product_node.get("title")
                
                variant_edges = product_node.get("variants", {}).get("edges", [])
                for v_edge in variant_edges:
                    v_node = v_edge.get("node", {})
                    all_variants.append({
                        "product_id": product_id,
                        "product_title": product_title,
                        "variant_id": v_node.get("id"),
                        "variant_title": v_node.get("title"),
                        "sku": v_node.get("sku"),
                        "price": v_node.get("price"),
                        "compare_at_price": v_node.get("compareAtPrice"),
                        "inventory_quantity": v_node.get("inventoryQuantity"),
                    })
            
            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")
            
        return all_variants

    async def get_variant_by_id(self, variant_gid: str) -> Optional[dict]:
        """
        Fetch a single variant by its GID.
        """
        query = """
        query getVariant($id: ID!) {
          productVariant(id: $id) {
            id
            sku
            price
            compareAtPrice
          }
        }
        """
        variables = {"id": variant_gid}
        
        try:
            data = await self._graphql(query, variables)
            await asyncio.sleep(0.5)
            
            if "errors" in data:
                logger.error(f"Error fetching variant {variant_gid}: {data['errors']}")
                return None
                
            return data.get("data", {}).get("productVariant")
        except Exception as e:
            logger.error(f"Error in get_variant_by_id for {variant_gid}: {e}")
            return None

    async def update_variant_price(self, variant_gid: str, price: str, compare_at_price: Optional[str] = None) -> dict:
        """
        Run the productVariantUpdate GraphQL mutation.
        """
        query = """
        mutation productVariantUpdate($input: ProductVariantInput!) {
          productVariantUpdate(input: $input) {
            productVariant {
              id
              price
              compareAtPrice
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        input_data = {
            "id": variant_gid,
            "price": price
        }
        if compare_at_price is not None:
            input_data["compareAtPrice"] = compare_at_price
            
        variables = {"input": input_data}
        
        result = {
            "success": False,
            "variant_id": None,
            "price": None,
            "errors": []
        }
        
        try:
            data = await self._graphql(query, variables)
            await asyncio.sleep(0.5)
            
            if "errors" in data:
                result["errors"] = data["errors"]
                return result
                
            mutation_result = data.get("data", {}).get("productVariantUpdate", {})
            user_errors = mutation_result.get("userErrors", [])
            
            if user_errors:
                result["errors"] = user_errors
            else:
                variant = mutation_result.get("productVariant", {})
                result["success"] = True
                result["variant_id"] = variant.get("id")
                result["price"] = variant.get("price")
                
        except Exception as e:
            logger.error(f"Error updating variant price for {variant_gid}: {e}")
            result["errors"] = [{"message": str(e)}]
            
        return result
