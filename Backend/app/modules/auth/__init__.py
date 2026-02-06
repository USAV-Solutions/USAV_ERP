"""
Authentication module.
Handles user authentication, authorization, and user management.
"""
from app.modules.auth.routes import router as auth_router

__all__ = ["auth_router"]
