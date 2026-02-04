### Step 1: Frontend Redirect

* **User Action:** Clicks "Login with SeaTalk".
* **SeaTalk Action:** Authenticates user and redirects to your backend.
* **URL:** `http://localhost:3636/auth/seatalk/callback?code=123...`

### Step 2: Get App Access Token (Backend)

* **Goal:** Get the "Key Card" to call SeaTalk APIs.
* **Request:** `POST https://openapi.seatalk.io/auth/app_access_token`
* **Result:** You get an `app_access_token`.
* *Tip: Cache this token! It lasts for 2 hours (7200s), so you don't need to call this every single time a user logs in.*



### Step 3: Verify Login & Get User Data (Backend)

* **Goal:** Exchange the `code` for the user's identity.
* **Request:** `GET https://openapi.seatalk.io/open_login/code2employee?code=[CODE_FROM_URL]`
* **Headers:** `Authorization: Bearer [TOKEN_FROM_STEP_2]`
* **Response:**
```json
{
  "code": 0,
  "employee": {
    "employee_code": "123",  <-- This is your "SeaTalk ID"
    "name": "Morgan Jackman",
    "email": "Morgan.Jackman@example.email.com" <-- Use this for matching
  }
}

```



### Step 4: Database Logic (Simplified)

Now that you have the `email` and `employee_code` from Step 3, run your logic:

1. **Check 1 (Existing Link):**
* Query DB: `SELECT * FROM users WHERE seatalk_id = '123'`
* **If found:** Log them in immediately.


2. **Check 2 (Link via Email):**
* Query DB: `SELECT * FROM users WHERE email = 'Morgan.Jackman@example.email.com'`
* **If found:**
* UPDATE the user: Set `seatalk_id = '123'`.
* Log them in.




3. **Check 3 (New User):**
* **If neither found:**
* INSERT new user:
* `name`: "Morgan Jackman"
* `email`: "Morgan.Jackman@example.email.com"
* `seatalk_id`: "123"
* `role`: "Sales Rep" (Default)


* Log them in.