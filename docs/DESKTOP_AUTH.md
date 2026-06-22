# Desktop Auth Notes

The desktop backend owns Stimma Cloud auth. It exchanges the desktop login code for Firebase tokens, stores the refresh token in OS credential storage when available, and keeps short-lived ID tokens in memory only.

If OS credential storage is unavailable, the backend logs the fallback and keeps the refresh token in process memory only. It does not create a plaintext token fallback file.

Remote logout/session revocation is optional until Stimma Cloud exposes it. The desktop app currently makes a best-effort call to:

```http
POST /api/auth/desktop/logout
Authorization: Bearer <firebase-id-token>
```

Expected cloud behavior:

- Verify the Firebase ID token.
- Revoke refresh tokens for the authenticated Firebase user.
- Return `200`, `202`, or `204`.
- Treat repeat calls as safe.

Desktop logout treats `404`, `405`, and network failures as non-fatal and always clears local auth material.
