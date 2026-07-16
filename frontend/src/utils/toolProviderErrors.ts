export type ToolProviderError = {
  title: string
  message: string
}

function endpointLabel(url?: string | null): string {
  const value = String(url || '').trim()
  return value || 'the provider'
}

function stripConnectionPrefixes(message: string): string {
  let cleaned = message.trim()
  let previous = ''
  while (cleaned !== previous) {
    previous = cleaned
    cleaned = cleaned.replace(/^(?:failed|unable) to connect(?:\s+to\s+[^:]+)?\s*:\s*/i, '').trim()
  }
  return cleaned
}

function ensureSentence(message: string): string {
  const cleaned = message.trim().replace(/[.\s]+$/, '')
  if (!cleaned) return 'Check the connection settings and try again.'
  return `${cleaned}.`
}

export function formatToolProviderConnectionError(rawError: unknown, url?: string | null): ToolProviderError {
  const raw = String(rawError || '').trim()
  const endpoint = endpointLabel(url)
  const lower = raw.toLowerCase()

  if (/nodename nor servname|name or service not known|getaddrinfo|no such host|temporary failure in name resolution/.test(lower)) {
    return {
      title: 'Server not found',
      message: `We couldn’t find ${endpoint}. Check the address and try again.`,
    }
  }

  if (/connection refused|connect call failed|actively refused/.test(lower)) {
    return {
      title: 'Provider isn’t running',
      message: `Nothing responded at ${endpoint}. Start the provider and try again.`,
    }
  }

  if (/timed? out|timeout/.test(lower)) {
    return {
      title: 'Connection timed out',
      message: `${endpoint} took too long to respond. Check that it is running and reachable.`,
    }
  }

  if (/unauthorized|forbidden|invalid (?:api )?key|invalid token|authentication|\b401\b|\b403\b/.test(lower)) {
    return {
      title: 'Authentication failed',
      message: 'The provider rejected the connection. Check the token and try again.',
    }
  }

  if (/invalid url|invalid uri|scheme|websocket url/.test(lower)) {
    return {
      title: 'Invalid address',
      message: 'Enter a valid WebSocket address and try again.',
    }
  }

  if (/certificate|ssl|tls/.test(lower)) {
    return {
      title: 'Secure connection failed',
      message: `Stimma couldn’t verify the secure connection to ${endpoint}.`,
    }
  }

  const cleaned = stripConnectionPrefixes(raw)
  return {
    title: 'Couldn’t connect',
    message: ensureSentence(cleaned),
  }
}
