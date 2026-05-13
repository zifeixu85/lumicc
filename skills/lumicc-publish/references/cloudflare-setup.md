# Cloudflare Pages setup for lumicc-publish

This skill deploys HTML to **Cloudflare Pages** (free tier: 500 builds/month,
unlimited bandwidth). You need two secrets:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

Both must be stored via the Lumicc secret form — **never paste them into the
chat or into CLI arguments**.

## 1. Create a Cloudflare account

[https://dash.cloudflare.com/sign-up](https://dash.cloudflare.com/sign-up) — free, no credit card.

## 2. Find your Account ID

1. Log in to [dash.cloudflare.com](https://dash.cloudflare.com).
2. Click any domain (or just the Workers & Pages tab in the sidebar).
3. The Account ID is shown in the right-hand panel — a 32-char hex string.

Store it:

```bash
python3 ../lumicc/scripts/secret_form.py --generate CLOUDFLARE_ACCOUNT_ID --open
```

## 3. Create an API Token with Pages permissions

1. Go to [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens).
2. Click **Create Token** → **Custom token**.
3. Permissions:
   - `Account` → `Cloudflare Pages` → `Edit`
4. Account Resources: include your account.
5. Click **Continue to summary** → **Create Token**.
6. Copy the token immediately (Cloudflare only shows it once).

Store it:

```bash
python3 ../lumicc/scripts/secret_form.py --generate CLOUDFLARE_API_TOKEN --open
```

Both writes go to `~/.commerce-os/secrets/*.json` (mode 0600). The form runs
entirely in your browser — no network request is made.

## 4. Optional: install `wrangler` for better DX

`lumicc-publish` prefers `wrangler` CLI if it's on `$PATH` — falls back to
direct HTTP API otherwise.

```bash
npm install -g wrangler
wrangler login
```

## 5. Verify

```bash
python3 scripts/run.py --html /tmp/test.html --public --dry-run
```

Dry-run skips the HTTP call but writes a row to the local `shares` table, so
you can confirm the wiring before spending API quota.

## Encryption notes

- The skill uses **AES-GCM 256** with **PBKDF2-SHA256 (600,000 iterations)** —
  OWASP 2023 recommendation.
- Python side requires `pip install cryptography`. Public deploys
  (`--public`) work on pure stdlib alone.
- Browser side uses WebCrypto SubtleCrypto, zero deps.
- Cloudflare sees only ciphertext + the wrapper UI. Decryption happens in the
  visitor's browser after they type the password.

## Limits / caveats

- Each Cloudflare project name must be unique within your account.
  `lumicc-publish` generates `lumicc-<random>` by default; pass `--subdomain`
  for stable names.
- Pages assets are served from CDN with TTL — `--revoke` flips a flag in the
  local DB but does NOT immediately purge the CDN. To hard-purge, also delete
  the project in the Cloudflare dashboard or via `wrangler pages project delete`.
- Free tier deployments are public-readable at the `*.pages.dev` URL. The
  password gate is **client-side** — relying on it means trusting AES-GCM.
- The password fingerprint stored in `~/.commerce-os/store.db` is
  `sha256(password)[:8]` — never the password itself.
