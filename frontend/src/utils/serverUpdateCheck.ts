type FetchLike = (input: string, init?: RequestInit) => Promise<Response>

/** Best-effort companion check for a headless server connected to the client. */
export async function triggerServerUpdateCheck(
  apiBase: string,
  request: FetchLike = fetch,
): Promise<boolean> {
  try {
    const status = await request(`${apiBase}/headless/status`, {
      signal: AbortSignal.timeout(10_000),
    })
    if (!status.ok || !(await status.json()).headless) return false

    const response = await request(`${apiBase}/headless/check`, {
      method: 'POST',
      signal: AbortSignal.timeout(15_000),
    })
    return response.ok
  } catch {
    // A server check must never prevent or fail the client updater check.
    return false
  }
}
