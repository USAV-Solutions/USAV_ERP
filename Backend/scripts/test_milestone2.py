import asyncio
from app.core.database import async_session_factory
from app.models.entities import ProductFamily, ProductIdentity, ProductVariant, PlatformListing, Platform, PlatformSyncStatus, IdentityType, PhysicalClass
from app.modules.inventory.routes.listings import get_variant_graph_topology, suggest_listing_matches, lock_listing_relationship, compare_listing_nodes
from app.modules.inventory.schemas.graph import AISuggestRequest, LockRelationshipRequest, CompareRequest
from sqlalchemy import delete

async def test_milestone2():
    async with async_session_factory() as session:
        # Pre-cleanup in case of earlier abort
        await session.execute(delete(PlatformListing).where(PlatformListing.external_ref_id.in_(["123456", "gid://shopify/ProductVariant/999888"])))
        await session.execute(delete(ProductVariant).where(ProductVariant.full_sku == "99991-P-1-BK-N"))
        await session.execute(delete(ProductIdentity).where(ProductIdentity.generated_upis_h == "99991-Product"))
        await session.execute(delete(ProductFamily).where(ProductFamily.product_id == 99991))
        await session.commit()

        # 1. Create a dummy Family, Identity, Variant, and Platform Listing for testing
        family = ProductFamily(product_id=99991, family_code="99991", base_name="Bose Wave Test System")
        session.add(family)
        await session.flush()

        identity = ProductIdentity(
            product_id=99991,
            type=IdentityType.PRODUCT,
            physical_class=PhysicalClass.E,
            identity_name="Bose Wave Test Unit",
            generated_upis_h="99991-Product",
            hex_signature="A1B2C3D4"
        )
        session.add(identity)
        await session.flush()

        variant = ProductVariant(
            identity_id=identity.id,
            full_sku="99991-P-1-BK-N",
            variant_name="Bose Wave Music System AWRCC1 - Black",
            color_code="BK"
        )
        session.add(variant)
        await session.flush()

        # Link one listing (Ecwid)
        ecwid_listing = PlatformListing(
            variant_id=variant.id,
            platform=Platform.ECWID,
            external_ref_id="123456",
            merchant_sku="99991-P-1-BK-N",
            listed_name="Bose Wave Music System Black (Ecwid)",
            listing_price=249.99,
            listing_quantity=5,
            sync_status=PlatformSyncStatus.SYNCED
        )
        session.add(ecwid_listing)

        # Unlinked Shopify listing (similar name)
        shopify_listing = PlatformListing(
            variant_id=None,
            platform=Platform.SHOPIFY,
            external_ref_id="gid://shopify/ProductVariant/999888",
            merchant_sku="00004-G",
            listed_name="Bose Wave Music System AWRCC1 - Default Title",
            listing_price=298.00,
            listing_quantity=2,
            sync_status=PlatformSyncStatus.PENDING
        )
        session.add(shopify_listing)
        await session.commit()

        print(f"Created test product: VariantID={variant.id}, EcwidListingID={ecwid_listing.id}, ShopifyListingID={shopify_listing.id}")

        try:
            # Test 1: Graph Topology
            print("\n--- TEST 1: Graph Topology ---")
            graph = await get_variant_graph_topology(variant.id, _user=None, db=session)
            print(f"Product Node: {graph.product.full_sku} ({graph.product.family_name})")
            print(f"Listings ({len(graph.listings)}): {[l.listed_name for l in graph.listings]}")
            print(f"Edges ({len(graph.edges)}): {graph.edges}")
            assert len(graph.listings) == 1
            assert graph.product.variant_id == variant.id

            # Test 2: AI Suggestion
            print("\n--- TEST 2: AI Match Suggestion ---")
            suggest_req = AISuggestRequest(variant_id=variant.id, limit=5)
            suggestions = await suggest_listing_matches(suggest_req, _user=None, db=session)
            print(f"Target: {suggestions.variant_sku} - {suggestions.variant_name}")
            print(f"Suggestions Count: {len(suggestions.suggestions)}")
            for s in suggestions.suggestions[:3]:
                print(f"  Candidate ID={s.listing_id}, Platform={s.platform.value}, Name={s.listed_name!r}, Confidence={s.confidence}, Reasons={s.reasons}")
            assert len(suggestions.suggestions) > 0

            # Test 3: Lock Relationship
            print("\n--- TEST 3: Lock Relationship ---")
            lock_req = LockRelationshipRequest(listing_id=shopify_listing.id, variant_id=variant.id, enrich_metadata=True)
            lock_res = await lock_listing_relationship(lock_req, _user=None, db=session)
            print(f"Lock Result: success={lock_res.success}, message={lock_res.message}")
            assert lock_res.success is True

            # Verify graph now has 2 listings
            graph_after = await get_variant_graph_topology(variant.id, _user=None, db=session)
            print(f"Graph listings count after lock: {len(graph_after.listings)}")
            assert len(graph_after.listings) == 2

            # Test 4: Compare Nodes
            print("\n--- TEST 4: Compare Listing Nodes ---")
            comp_req = CompareRequest(listing_ids=[ecwid_listing.id, shopify_listing.id])
            comp_res = await compare_listing_nodes(comp_req, _user=None, db=session)
            print(f"Compared {len(comp_res.listings)} listings across {len(comp_res.comparison_fields)} metric fields:")
            for f in comp_res.comparison_fields[:5]:
                print(f"  {f.label}: {f.values}")
            assert len(comp_res.listings) == 2

        finally:
            # Cleanup test data
            await session.delete(ecwid_listing)
            await session.delete(shopify_listing)
            await session.delete(variant)
            await session.delete(identity)
            await session.delete(family)
            await session.commit()
            print("\nALL MILESTONE 2 TESTS PASSED PERFECTLY!")

if __name__ == "__main__":
    asyncio.run(test_milestone2())
