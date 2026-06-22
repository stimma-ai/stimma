# Desktop Auth Notes

The desktop backend owns Stimma Cloud auth. It exchanges the desktop login code for Firebase tokens, stores the refresh token outside `cloud_auth.json`, and keeps short-lived ID tokens in memory only.

Refresh-token storage by platform:

- macOS: user Keychain.
- Windows: Credential Manager generic credential.
- Linux: Freedesktop Secret Service over DBus when available.

On Linux, if Secret Service is unavailable in the AppImage/runtime environment, the backend logs the downgrade and stores the refresh token in a managed fallback file named `cloud_auth_tokens.json` with `0600` permissions in the app data directory. This preserves login persistence while keeping token material out of the display/cache state file.

On unsupported platforms, or if both the platform store and the Linux fallback fail, the backend logs the fallback and keeps the refresh token in process memory only.

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
