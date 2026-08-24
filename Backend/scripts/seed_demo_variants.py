import asyncio
from app.core.database import async_session_factory
from app.models.entities import ProductFamily, ProductIdentity, ProductVariant, PlatformListing, ConditionCode, PlatformSyncStatus, Platform, IdentityType
from sqlalchemy import select

async def seed_demo():
    async with async_session_factory() as session:
        # Check if already seeded
        existing = await session.execute(select(ProductVariant).limit(1))
        if existing.scalar_one_or_none():
            print("Variants already exist in database.")
            return

        # 1. Create Family 1: Bose Wave Music System (product_id=4)
        f1 = ProductFamily(
            product_id=4,
            family_code="00004",
            base_name="Bose Wave Music System",
        )
        session.add(f1)
        await session.flush()

        # Identity 1
        i1 = ProductIdentity(
            product_id=f1.product_id,
            identity_name="Bose Wave Music System AWRCC1",
            type=IdentityType.PRODUCT,
            generated_upis_h="00004-Product-1",
            hex_signature="00004001",
        )
        session.add(i1)
        await session.flush()

        # Variant 1 (00004-G)
        v1 = ProductVariant(
            identity_id=i1.id,
            full_sku="00004-G",
            variant_name="Bose Wave Music System AWRCC1 Graphite",
            color_code="GR",
            condition_code=ConditionCode.U,
            is_active=True,
        )
        session.add(v1)

        # 2. Create Family 2: Bose 321 Series II (product_id=1)
        f2 = ProductFamily(
            product_id=1,
            family_code="00001",
            base_name="Bose 321 Series II Home Entertainment System",
        )
        session.add(f2)
        await session.flush()

        # Identity 2
        i2 = ProductIdentity(
            product_id=f2.product_id,
            identity_name="Bose 321 Series II System",
            type=IdentityType.PRODUCT,
            generated_upis_h="00001-Product-1",
            hex_signature="00001001",
        )
        session.add(i2)
        await session.flush()

        # Variant 2 (00000-01) - Refurbished
        v2 = ProductVariant(
            identity_id=i2.id,
            full_sku="00000-01",
            variant_name="Bose 321 Series II USAV Refurbished",
            color_code="BK",
            condition_code=ConditionCode.R,
            is_active=True,
        )
        session.add(v2)

        # Variant 3 (00000-02) - Grade B
        v3 = ProductVariant(
            identity_id=i2.id,
            full_sku="00000-02",
            variant_name="Bose 321 Series II Grade B",
            color_code="BK",
            condition_code=ConditionCode.U,
            is_active=True,
        )
        session.add(v3)

        await session.flush()

        # Link listing 1 to Variant 1
        l1 = await session.get(PlatformListing, 1)
        if l1:
            l1.variant_id = v1.id
            l1.sync_status = PlatformSyncStatus.SYNCED
            print(f"Linked Listing #{l1.id} to Variant #{v1.id} ({v1.full_sku})")

        # Link listing 7 to Variant 2
        l7 = await session.get(PlatformListing, 7)
        if l7:
            l7.variant_id = v2.id
            l7.sync_status = PlatformSyncStatus.SYNCED
            print(f"Linked Listing #{l7.id} to Variant #{v2.id} ({v2.full_sku})")

        # Also add an eBay & Ecwid listing linked to Variant 1 for rich multi-channel graph demo
        ebay_listing = PlatformListing(
            platform=Platform.EBAY_USAV,
            external_ref_id="ebay-184920491823",
            merchant_sku="00004-G",
            listed_name="Bose Wave Music System AWRCC1 CD Radio - Tested & Working",
            listing_price=319.99,
            listing_quantity=2,
            sync_status=PlatformSyncStatus.SYNCED,
            variant_id=v1.id,
        )
        session.add(ebay_listing)

        ecwid_listing = PlatformListing(
            platform=Platform.ECWID,
            external_ref_id="ecwid-9382103",
            merchant_sku="00004-G",
            listed_name="Bose Wave Music System AWRCC1 Graphite Gray",
            listing_price=298.00,
            listing_quantity=1,
            sync_status=PlatformSyncStatus.SYNCED,
            variant_id=v1.id,
        )
        session.add(ecwid_listing)

        await session.commit()
        print("Successfully seeded demo product variants and multi-channel graph relationships!")

if __name__ == "__main__":
    asyncio.run(seed_demo())
