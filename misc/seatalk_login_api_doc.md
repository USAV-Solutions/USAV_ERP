# Integrate Login With SeaTalk to Your Website

In this article, we will guide you through integrating the **Login With SeaTalk** capability into your website.

## What Can Login With SeaTalk Capability Do?

Login With SeaTalk allows users to log in to your website using their SeaTalk account—similar to logging in with Google, Facebook, or other third-party accounts.

We follow the **OAuth 2.0** standard to provide the relevant technical foundations and protocols when handling sensitive user information.

---

## Step 1: Create an SOP App

From **open.seatalk.io**, click **Start building** or **Create app** to trigger the app creation wizard.  
You can also click **Create app** from your app list.

Follow the wizard steps to complete the basic configuration of your app.

### Step 1.1: Basic App Information

*(Configure your app’s basic information in the wizard)*

### Step 1.2: Service and Data Scope Configuration

After creation, your new app will have a default status of **Not Configured**.  
Learn more about app statuses if needed.

Click the **Enable** button in the **Login with SeaTalk** card under the **Capability** section.

Once the capability is successfully enabled:

- It will appear in the left-hand menu
- You will be redirected to the capability configuration page
- Default API permissions for this capability will be automatically enabled

---

## Step 2: Configure Redirect URI

Navigate to the **Login With SeaTalk** section and configure a **Redirect URI** that exactly matches your service endpoint.

The Redirect URI determines which endpoint can receive the authentication code used to exchange for user identity.

---

## Step 3: Add Login Button Using SeaTalk JS Framework

You can easily add a standard **Login with SeaTalk** button to your website using the provided HTML and JavaScript library.

When a user clicks the login button, they will be redirected to the SeaTalk Login Page.

### Example Code Snippet

```html
<div id="seatalk_login_app_info"
     data-redirect_uri="[YOUR_REDIRECT_URI]"
     data-appid="[YOUR_APPID]"
     data-response_type="code"
     data-state="[STATE]">
</div>

<div id="seatalk_login_button"
     data-size="small"
     data-logo_size="22"
     data-copywriting="Continue with SeaTalk"
     data-theme="light"
     data-align="center">
</div>

<script src="https://static.cdn.haiserve.com/seatalk/client/shared/sop/auth.js"></script>
```

## App Information Configuration (`seatalk_login_app_info`)

This element specifies your app information on the SeaTalk Open Platform.

| Data Attribute       | Value  | Mandatory | Description                                                          |
| -------------------- | ------ | --------- | -------------------------------------------------------------------- |
| `data-appid`         | String | Yes       | Your app’s unique App ID                                             |
| `data-redirect_uri`  | String | Yes       | Redirect endpoint after successful authorization                     |
| `data-response_type` | code   | Yes       | Authorized type (must be `code`)                                     |
| `data-state`         | String | No        | Used to maintain state and prevent request forgery (CSRF protection) |

---

## Login Button Configuration (`seatalk_login_button`)

This element renders the **Login With SeaTalk** button and allows customization.

| Data Attribute     | Value Options                 | Mandatory | Description                                 |
| ------------------ | ----------------------------- | --------- | ------------------------------------------- |
| `data-size`        | `small` | `default` | `large` | No        | Button size                                 |
| `data-align`       | `center` | `border`           | No        | Icon and text alignment (default: `center`) |
| `data-theme`       | `default` | `dark`            | No        | Button theme                                |
| `data-logo_size`   | String                        | No        | SeaTalk logo size (default: 22px)           |
| `data-copywriting` | String                        | No        | Button text (default: *Login with SeaTalk*) |

SeaTalk Open Platform also provides design guidelines for the button.
Refer to **Button Design Guidelines** for details.

---

## Step 4: Get User Identity

After users grant permission on the SeaTalk Login Page, they will be redirected to the URI specified in `data-redirect_uri`.

An **authorization code** will be appended to the redirect URI, for example:

```
https://www.yourwebsite.com/?code=1f2b62b4210448a19ac1a83da59fb32c&state=test
```

* The authorization code acts as a temporary token
* It expires after **10 minutes**
* Use this code to retrieve user profile information by calling the **Verify Login with SeaTalk Code API**

---

## What’s Next

You have now successfully integrated your app with the **Login With SeaTalk** capability 🎉

Additional options:

* **Get employee profile information**
  Apply for permission to use the *Get Employee Profile API*:
  [https://open.seatalk.io/docs/build-an-app-for-your-team](https://open.seatalk.io/docs/build-an-app-for-your-team)

* **Allow more users to log in**
  Apply for additional service scopes:
  [https://open.seatalk.io/docs/build-an-app-for-your-team](https://open.seatalk.io/docs/build-an-app-for-your-team)

* **Learn more about Login With SeaTalk**
  [https://open.seatalk.io/docs/login-with-seatalk-overview](https://open.seatalk.io/docs/login-with-seatalk-overview)

