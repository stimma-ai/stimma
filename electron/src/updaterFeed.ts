export function updaterFeedConfiguration(url: string) {
  return {
    provider: 'generic' as const,
    url,
    // Cloudflare R2 supports byte ranges, but rejects multipart Range headers.
    // Keep differential downloads enabled using one range per request.
    useMultipleRangeRequest: false,
  }
}
