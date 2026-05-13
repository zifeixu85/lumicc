# API Credentials Setup

Cross-Border Commerce OS never asks for credentials directly. Instead, the OS expects them in your shell environment or in `~/.commerce-os/.env`. Sub-skills load them via `scripts/memory.py:load_env()`.

## ⚠️ Security

- **Never** paste credentials into chat with the agent.
- **Never** commit `.env` to git.
- Store API keys with read-only scopes when possible.
- Rotate at least quarterly.

## Shopify (Custom App pattern)

1. Login to https://admin.shopify.com → your store
2. Settings → Apps and sales channels → "Develop apps"
3. Create a Custom App → set Admin API scopes:
   - `read_products`, `write_products`
   - `read_orders` (recommended)
   - `read_content`, `write_content` (for themes/blogs)
   - `read_inventory`, `write_inventory`
4. Install → copy the **Admin API access token** (`shpat_...`)
5. Save to `~/.commerce-os/.env`:
   ```
   SHOPIFY_STORE_DOMAIN=yourstore.myshopify.com
   SHOPIFY_ADMIN_TOKEN=shpat_xxxxxxxx
   ```

See Shopify's official docs: https://shopify.dev/docs/apps/auth/oauth.

## Amazon SP-API

1. Register as Amazon Developer: https://developer-docs.amazon.com/sp-api/
2. Create LWA (Login with Amazon) credentials + IAM user
3. Get refresh token via OAuth flow
4. Save:
   ```
   AMAZON_LWA_CLIENT_ID=...
   AMAZON_LWA_CLIENT_SECRET=...
   AMAZON_LWA_REFRESH_TOKEN=...
   AMAZON_SP_API_ROLE_ARN=...
   AMAZON_REGION=na | eu | fe
   ```

## TikTok Shop Open Platform

1. Apply at https://partner.tiktokshop.com
2. Approve as developer → create app
3. Get app_key + app_secret + shop_id
4. OAuth flow gets `access_token` (28-day refresh)
5. Save:
   ```
   TIKTOK_SHOP_APP_KEY=...
   TIKTOK_SHOP_APP_SECRET=...
   TIKTOK_SHOP_ACCESS_TOKEN=...
   TIKTOK_SHOP_REGION=us | uk | sea
   ```

## Etsy Open API

1. https://www.etsy.com/developers/your-apps → create app
2. OAuth2 flow → get access + refresh token
3. Save:
   ```
   ETSY_API_KEY=...
   ETSY_SHARED_SECRET=...
   ETSY_ACCESS_TOKEN=...
   ETSY_REFRESH_TOKEN=...
   ```

## Jungle Scout (Amazon analytics)

1. https://www.junglescout.com/api/
2. Generate API key in dashboard
3. Save:
   ```
   JUNGLE_SCOUT_API_KEY=...
   ```

## 1688 / Alibaba (for sourcing)

Casual matching via the public web UI does not require a developer key. For programmatic access:

- 1688: https://open.1688.com → developer apply
- Alibaba: https://openapi.alibaba.com

## Klaviyo (EDM)

```
KLAVIYO_PRIVATE_API_KEY=pk_...
```

## Stripe / PayPal (payments — usually not needed by OS)

OS does not handle payments. Skip unless a sub-skill explicitly requires.

## `~/.commerce-os/.env` Template

```ini
# Required for most sub-skills
SHOPIFY_STORE_DOMAIN=
SHOPIFY_ADMIN_TOKEN=

# Optional — fill what you have
AMAZON_LWA_CLIENT_ID=
AMAZON_LWA_CLIENT_SECRET=
AMAZON_LWA_REFRESH_TOKEN=

TIKTOK_SHOP_APP_KEY=
TIKTOK_SHOP_APP_SECRET=
TIKTOK_SHOP_ACCESS_TOKEN=

ETSY_API_KEY=
JUNGLE_SCOUT_API_KEY=
KLAVIYO_PRIVATE_API_KEY=

# OpenAI / Anthropic for content sub-skills (if not already in agent runtime)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

`scripts/health_check.py` validates which credentials are present and prints which sub-skills are unlocked.
