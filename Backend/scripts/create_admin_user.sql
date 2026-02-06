-- =============================================================================
-- USAV Inventory Database - Create Admin User
-- =============================================================================
-- This SQL script creates an admin user in the database.
--
-- IMPORTANT: You MUST hash the password using bcrypt before inserting!
-- The password hash below is an example only.
--
-- To generate a proper password hash, use the Python script:
--   python scripts/create_admin_user.py
-- 
-- Or use an online bcrypt generator (for testing only):
--   https://bcrypt-generator.com/
--
-- =============================================================================

-- Insert admin user
-- NOTE: Replace the hashed_password value with an actual bcrypt hash
INSERT INTO users (
    username,
    email,
    hashed_password,
    full_name,
    role,
    is_active,
    is_superuser,
    created_at,
    updated_at
) VALUES (
    'sysad',                          -- username
    'lebach.kara@gmail.com',              -- email (optional, can be NULL)
    '$2b$12$RNwVwlnRfvYPW.O4T8lVZ.BlSC29WRJBGl0PSYZ5nmgZOlVY2MR2K',                     -- hashed_password (bcrypt hash - REPLACE THIS!)
    'System Administrator',                  -- full_name (optional, can be NULL)
    'ADMIN',                          -- role (must be ADMIN, WAREHOUSE_OP, SALES_REP, or SYSTEM_BOT)
    true,                             -- is_active
    true,                             -- is_superuser
    CURRENT_TIMESTAMP,                -- created_at
    CURRENT_TIMESTAMP                 -- updated_at
);

-- =============================================================================
-- Alternative: Create additional users with different roles
-- =============================================================================

-- Warehouse Operator
INSERT INTO users (
    username,
    email,
    hashed_password,
    full_name,
    role,
    is_active,
    is_superuser
) VALUES (
    'warehouse_op',
    'warehouse@example.com',
    '$2b$12$...',  -- REPLACE WITH ACTUAL BCRYPT HASH
    'Warehouse Operator',
    'WAREHOUSE_OP',
    true,
    false
);

-- Sales Representative
INSERT INTO users (
    username,
    email,
    hashed_password,
    full_name,
    role,
    is_active,
    is_superuser
) VALUES (
    'sales_rep',
    'sales@example.com',
    '$2b$12$...',  -- REPLACE WITH ACTUAL BCRYPT HASH
    'Sales Representative',
    'SALES_REP',
    true,
    false
);

-- System Bot
INSERT INTO users (
    username,
    email,
    hashed_password,
    full_name,
    role,
    is_active,
    is_superuser
) VALUES (
    'system_bot',
    NULL,
    '$2b$12$...',  -- REPLACE WITH ACTUAL BCRYPT HASH
    'System Bot',
    'SYSTEM_BOT',
    true,
    false
);

-- =============================================================================
-- Verify the users were created
-- =============================================================================
SELECT id, username, email, role, is_active, is_superuser, created_at 
FROM users 
ORDER BY created_at DESC;
