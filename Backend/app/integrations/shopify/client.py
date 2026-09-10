"""
Shopify API Client.

Implements integration with Shopify platform for price synchronization.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List

import httpx

from app.integrations.base import (
    BasePlatformClient,
    ExternalOrder,
    ExternalOrderItem,
    StockUpdate,
    StockUpdateResult,
)

logger = logging.getLogger(__name__)


class ShopifyClient(BasePlatformClient):
    """
    Shopify Admin GraphQL API client for price synchronization and order ingestion.
    
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

    @property
    def platform_name(self) -> str:
        """Return the platform identifier."""
        return "SHOPIFY"

    @property
    def is_configured(self) -> bool:
        """Check if client has required credentials."""
        return bool(self.shop_url and self.access_token)

    async def authenticate(self) -> bool:
        """Authenticate with Shopify."""
        if not self.is_configured:
            return False
        conn = await self.test_connection()
        return bool(conn.get("success"))

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

    def _parse_money(self, val_set: Optional[dict]) -> float:
        if not val_set:
            return 0.0
        shop_money = val_set.get("shopMoney") or {}
        try:
            return float(shop_money.get("amount") or 0.0)
        except (ValueError, TypeError):
            return 0.0

    def _parse_shopify_order(self, node: dict) -> ExternalOrder:
        order_id = node.get("id", "")
        order_number = node.get("name") or None

        customer = node.get("customer") or {}
        shipping = node.get("shippingAddress") or {}

        first_name = customer.get("firstName") or ""
        last_name = customer.get("lastName") or ""
        customer_name = f"{first_name} {last_name}".strip() or shipping.get("name") or None
        customer_email = customer.get("email") or node.get("email") or None
        customer_phone = customer.get("phone") or shipping.get("phone") or None
        customer_company = shipping.get("company") or None
        customer_external_id = customer.get("id") or None

        ship_line1 = shipping.get("address1") or None
        ship_line2 = shipping.get("address2") or None
        ship_city = shipping.get("city") or None
        ship_state = shipping.get("provinceCode") or shipping.get("province") or None
        ship_zip = shipping.get("zip") or None
        ship_country = shipping.get("countryCodeV2") or shipping.get("country") or "US"

        subtotal = self._parse_money(node.get("subtotalPriceSet"))
        tax = self._parse_money(node.get("totalTaxSet"))
        shipping_amt = self._parse_money(node.get("totalShippingPriceSet"))
        total = self._parse_money(node.get("totalPriceSet"))
        currency = node.get("currencyCode") or "USD"

        created_at_str = node.get("createdAt")
        ordered_at = None
        if created_at_str:
            try:
                ordered_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            except Exception as e:
                logger.warning(f"Failed to parse Shopify createdAt '{created_at_str}': {e}")

        tracking_number = None
        carrier = None
        for f in node.get("fulfillments") or []:
            for t in f.get("trackingInfo") or []:
                if t.get("number"):
                    tracking_number = t.get("number")
                    carrier = t.get("company")
                    break
            if tracking_number:
                break

        items: List[ExternalOrderItem] = []
        line_edges = (node.get("lineItems") or {}).get("edges", [])
        for l_edge in line_edges:
            l_node = l_edge.get("node") or {}
            l_variant = l_node.get("variant") or {}
            variant_id = l_variant.get("id")
            line_id = l_node.get("id")
            qty = int(l_node.get("quantity") or 1)
            unit_price = self._parse_money(l_node.get("originalUnitPriceSet"))
            line_total = self._parse_money(l_node.get("discountedTotalSet"))
            if line_total == 0.0 and unit_price > 0.0:
                line_total = round(unit_price * qty, 2)

            items.append(
                ExternalOrderItem(
                    platform_item_id=variant_id or line_id,
                    platform_sku=l_node.get("sku") or None,
                    asin=None,
                    title=l_node.get("title") or "Shopify Line Item",
                    quantity=qty,
                    unit_price=unit_price,
                    total_price=line_total,
                    raw_data=l_node,
                )
            )

        return ExternalOrder(
            platform_order_id=order_id,
            platform_order_number=order_number,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_external_id=customer_external_id,
            customer_phone=customer_phone,
            customer_company=customer_company,
            customer_source="SHOPIFY_API",
            ship_address_line1=ship_line1,
            ship_address_line2=ship_line2,
            ship_address_line3=None,
            ship_city=ship_city,
            ship_state=ship_state,
            ship_postal_code=ship_zip,
            ship_country=ship_country,
            subtotal=subtotal,
            tax=tax,
            shipping=shipping_amt,
            total=total,
            currency=currency,
            ordered_at=ordered_at,
            items=items,
            raw_data=node,
            tracking_number=tracking_number,
            carrier=carrier,
        )

    async def fetch_orders(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> List[ExternalOrder]:
        """
        Fetch orders from Shopify via GraphQL.
        """
        if not self.is_configured:
            logger.warning("Shopify client not configured, cannot fetch orders")
            return []

        query_parts = []
        if status:
            query_parts.append(f"status:{status}")
        else:
            query_parts.append("status:any")

        if since:
            since_utc = since.astimezone(timezone.utc) if since.tzinfo else since
            query_parts.append(f"created_at:>='{since_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}'")
        if until:
            until_utc = until.astimezone(timezone.utc) if until.tzinfo else until
            query_parts.append(f"created_at:<='{until_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}'")

        filter_query = " AND ".join(query_parts) if query_parts else None

        gql_query = """
        query getOrders($first: Int!, $cursor: String, $query: String) {
          orders(first: $first, after: $cursor, query: $query, sortKey: CREATED_AT) {
            pageInfo {
              hasNextPage
              endCursor
            }
            edges {
              node {
                id
                name
                createdAt
                currencyCode
                email
                subtotalPriceSet {
                  shopMoney {
                    amount
                  }
                }
                totalTaxSet {
                  shopMoney {
                    amount
                  }
                }
                totalShippingPriceSet {
                  shopMoney {
                    amount
                  }
                }
                totalPriceSet {
                  shopMoney {
                    amount
                  }
                }
                customer {
                  id
                  firstName
                  lastName
                  email
                  phone
                }
                shippingAddress {
                  name
                  address1
                  address2
                  city
                  provinceCode
                  province
                  zip
                  countryCodeV2
                  country
                  company
                  phone
                }
                fulfillments {
                  trackingInfo {
                    number
                    company
                  }
                }
                lineItems(first: 100) {
                  edges {
                    node {
                      id
                      sku
                      title
                      quantity
                      variant {
                        id
                      }
                      originalUnitPriceSet {
                        shopMoney {
                          amount
                        }
                      }
                      discountedTotalSet {
                        shopMoney {
                          amount
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """

        orders: List[ExternalOrder] = []
        cursor = None
        has_next_page = True

        while has_next_page:
            variables = {"first": 50, "cursor": cursor, "query": filter_query}
            try:
                data = await self._graphql(gql_query, variables)
            except Exception as e:
                logger.error(f"Failed to query Shopify orders: {e}")
                break

            await asyncio.sleep(0.5)

            if "errors" in data:
                logger.error(f"Shopify GraphQL error fetching orders: {data['errors']}")
                break

            orders_data = data.get("data", {}).get("orders", {})
            page_info = orders_data.get("pageInfo", {})
            edges = orders_data.get("edges", [])

            for edge in edges:
                node = edge.get("node")
                if node:
                    try:
                        orders.append(self._parse_shopify_order(node))
                    except Exception as parse_err:
                        logger.error(f"Failed to parse Shopify order {node.get('id')}: {parse_err}")

            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

        logger.info(f"Fetched {len(orders)} orders from Shopify")
        return orders

    async def get_order(self, order_id: str) -> Optional[ExternalOrder]:
        """Fetch single order by GID."""
        if not self.is_configured:
            return None

        gid = order_id if order_id.startswith("gid://") else f"gid://shopify/Order/{order_id}"

        gql_query = """
        query getOrder($id: ID!) {
          order(id: $id) {
            id
            name
            createdAt
            currencyCode
            email
            subtotalPriceSet {
              shopMoney {
                amount
              }
            }
            totalTaxSet {
              shopMoney {
                amount
              }
            }
            totalShippingPriceSet {
              shopMoney {
                amount
              }
            }
            totalPriceSet {
              shopMoney {
                amount
              }
            }
            customer {
              id
              firstName
              lastName
              email
              phone
            }
            shippingAddress {
              name
              address1
              address2
              city
              provinceCode
              province
              zip
              countryCodeV2
              country
              company
              phone
            }
            fulfillments {
              trackingInfo {
                number
                company
              }
            }
            lineItems(first: 100) {
              edges {
                node {
                  id
                  sku
                  title
                  quantity
                  variant {
                    id
                  }
                  originalUnitPriceSet {
                    shopMoney {
                      amount
                    }
                  }
                  discountedTotalSet {
                    shopMoney {
                      amount
                    }
                  }
                }
              }
            }
          }
        }
        """
        try:
            data = await self._graphql(gql_query, {"id": gid})
            node = data.get("data", {}).get("order")
            if node:
                return self._parse_shopify_order(node)
        except Exception as e:
            logger.error(f"Failed to fetch Shopify order {order_id}: {e}")
        return None

    async def update_stock(self, updates: List[StockUpdate]) -> List[StockUpdateResult]:
        """Stock level updates not implemented for Shopify."""
        return [
            StockUpdateResult(
                sku=u.sku,
                success=False,
                message="Stock update not implemented for Shopify",
                external_ref_id=u.external_ref_id,
            )
            for u in updates
        ]

    async def update_tracking(
        self,
        order_id: str,
        tracking_number: str,
        carrier: str
    ) -> bool:
        """Tracking updates not implemented for Shopify."""
        logger.warning(f"Shopify tracking update not implemented for order {order_id}")
        return False
