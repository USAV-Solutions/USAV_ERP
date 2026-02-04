# Verify Login With SeaTalk Code

## API Description

Use this API to exchange an authorization code—obtained via the Redirect URI configured with **Login With SeaTalk**—for a user’s basic information.

> **Note:** The authorization code expires after **10 minutes**.

---

## Request

### Request Method
`GET`

### Endpoint
```

[https://openapi.seatalk.io/open_login/code2employee](https://openapi.seatalk.io/open_login/code2employee)

```

---

## Request Parameters

### Header Parameters

| Parameter      | Type   | Mandatory | Description                                   | Default | Sample |
|----------------|--------|-----------|-----------------------------------------------|---------|--------|
| Authorization  | string | Yes       | Obtained from the Get App Access Token API     | N/A     | `Bearer c8bda0f77ef940c5bea9f23b2d7fc0d8` |

### Query Parameters

| Parameter | Type   | Mandatory | Description                                                       | Default | Sample |
|-----------|--------|-----------|-------------------------------------------------------------------|---------|--------|
| code      | string | Yes       | Obtained from the Redirect URI configured with Login With SeaTalk | N/A     | `"123"` |

---

## Request Sample


[https://openapi.seatalk.io/open_login/code2employee?code=123](https://openapi.seatalk.io/open_login/code2employee?code=123)

---

## Response Parameters

### Result Fields

| Parameter | Type | Description |
|----------|------|-------------|
| code     | int  | Refer to Error Code documentation for details |
| employee | object | Employee information |

### Employee Object Fields

| Field           | Type   | Description |
|-----------------|--------|-------------|
| employee_code   | string | Employee code |
| avatar          | string | SeaTalk avatar URL |
| name            | string | Employee name |
| email           | string | Employee email |
| mobile          | string | Employee mobile phone number |

---

## Response Sample

```json
{
  "code": 0,
  "employee": {
    "employee_code": "123",
    "avatar": "https://openapi.seatalk.io/file/employee/icon/beedfaa1e335e48293b2e5e624a413860b03010000012b0d0000000002010089",
    "name": "Morgan Jackman",
    "email": "Morgan.Jackman@example.email.com",
    "mobile": "+6593010285"
  }
}

