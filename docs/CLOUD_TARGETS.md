# Stimma Cloud Targets

Stimma source builds default to the public production Stimma Cloud endpoint from
`config.yaml`. Do not hardcode private staging hostnames or service tokens in
this repository.

For local development, the `tools/stimma` CLI loads an ignored repo-root
`.env.local` file for `stimma dev ...` and `stimma run ...` commands. Use that
file for private cloud target overrides on trusted machines.

Supported local variables:

```bash
STIMMA_CLOUD_BASE_URL=https://example.internal
STIMMA_CLOUD_ACCESS_CLIENT_ID=...
STIMMA_CLOUD_ACCESS_CLIENT_SECRET=...
```

The Cloudflare-compatible aliases `CF_ACCESS_CLIENT_ID`,
`CF_ACCESS_CLIENT_SECRET`, `CLOUDFLARE_ACCESS_CLIENT_ID`, and
`CLOUDFLARE_ACCESS_CLIENT_SECRET` are also accepted.

When these variables are present:

- the backend uses `STIMMA_CLOUD_BASE_URL` instead of the persisted
  `cloud.base_url` setting;
- Stimma-owned HTTP calls include Cloudflare Access service-token headers;
- the Stimma Cloud STP websocket and its relative asset requests include the
  same Access headers;
- the Tauri dev shell, frontend, and backend all receive the same local env
  when launched through `stimma dev all`.

The local env file is intentionally not used for release CI. Official canary,
beta, and production builds continue to use the normal production cloud target
unless their persisted user config says otherwise.
