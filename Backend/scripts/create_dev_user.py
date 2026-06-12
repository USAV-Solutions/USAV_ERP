import asyncio
import os
import sys

# Add backend directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.database import async_session_factory
from app.models.user import User, UserRole
from app.core.security import get_password_hash
from sqlalchemy import select

async def main():
    async with async_session_factory() as session:
        # Check if user admin exists
        stmt = select(User).where(User.username == "admin")
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        if user:
            print("User 'admin' already exists. Updating password...")
            user.hashed_password = get_password_hash("admin123")
            user.role = UserRole.ADMIN
            user.is_superuser = True
            await session.commit()
            print("Successfully updated 'admin' password to 'admin123'")
            return
        
        new_user = User(
            username="admin",
            hashed_password=get_password_hash("admin123"),
            email="admin@example.com",
            role=UserRole.ADMIN,
            is_active=True,
            is_superuser=True
        )
        session.add(new_user)
        await session.commit()
        print("Successfully created 'admin' user with password 'admin123'")

if __name__ == "__main__":
    asyncio.run(main())
