import asyncio
from app.core.database import async_session_factory
from app.models.user import User, UserRole
from app.core.security import get_password_hash
from sqlalchemy import select

async def main():
    async with async_session_factory() as db:
        res = await db.execute(select(User).where(User.username == 'packer1'))
        user = res.scalars().first()
        if not user:
            user = User(
                username='packer1',
                email='packer1@usavshop.com',
                full_name='Warehouse Packer',
                hashed_password=get_password_hash('packer123'),
                role=UserRole.PACKER,
                is_active=True,
            )
            db.add(user)
            await db.commit()
            print("User 'packer1' created successfully with password 'packer123'")
        else:
            user.role = UserRole.PACKER
            user.hashed_password = get_password_hash('packer123')
            await db.commit()
            print("User 'packer1' updated with PACKER role and password 'packer123'")

if __name__ == '__main__':
    asyncio.run(main())
