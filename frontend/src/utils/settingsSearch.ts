export interface SettingSearchHit {
  section: string
  sectionLabel: string
  label: string
  keywords: string
  target?: string
}

// User-facing labels and synonyms only; never index configured paths, keys or
// account data. Targets are explicit anchors, SettingRow labels or headings in the section.
const entries: Array<[string, string, Array<[string, string, string?]>]> = [
  ['folders', 'Folders', [['Folders', 'sources source folder watch scan rescan import storage']]],
  ['markers', 'Markers', [['Markers', 'tags labels colors icons auto mark']]],
  ['wildcards', 'Prompt variables', [['Wildcards', 'random prompt variables substitutions', 'prompt-wildcards'], ['Segments', 'fixed prompt text blocks substitutions', 'prompt-segments']]],
  ['agent', 'Agent', [['Models', 'agent model reasoning'], ['Default Instructions', 'system prompt instructions'], ['Memory', 'remember memories'], ['Tool Permissions', 'permissions approval tools']]],
  ['mcp', 'MCP', [['MCP', 'model context protocol integrations clients'], ['Direct connections', 'remote computers connections']]],
  ['account', 'Stimma account', [['Stimma Account', 'sign in login credits balance subscription billing cloud', 'stimma-account']]],
  ['shared-links', 'Shared links', [['Shared links', 'share published links revoke']]],
  ['server', 'Stimma server', [['Stimma Server', 'devices pairing remote headless connection'], ['Enable server', 'enable server network access']]],
  ['tools', 'Generation tools', [['Generation Tools', 'providers comfyui draw things local tools connection']]],
  ['ai-services', 'Chat models', [['Chat Models', 'llm api key openai anthropic chatgpt ollama provider endpoints']]],
  ['model-preferences', 'Preferences', [['Theme', 'appearance dark light system theme'], ['Image generation previews', 'live image preview'], ['Video generation previews', 'live video preview']]],
  ['profiles', 'Profiles', [['Profiles', 'profile create rename delete pin lock password']]],
  ['background', 'Background work', [['Face Detection', 'face recognition faces analysis'], ['Visual Indexing', 'clip semantic visual search indexing']]],
  ['stimpacks', 'Stimpacks', [['Stimpacks', 'skills install marketplace library extensions']]],
  ['privacy', 'Privacy', [['Privacy', 'privacy lockdown feedback sharing telemetry analytics']]],
  ['updates', 'About', [['About', 'version updates release channel downloads license attribution', 'about-build']]],
]

export function searchSettings(query: string): SettingSearchHit[] {
  const tokens = query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean)
  if (!tokens.length) return []
  return entries.flatMap(([section, sectionLabel, settings]) => settings.map(([label, keywords, target]) => ({ section, sectionLabel, label, keywords, target })))
    .filter(hit => tokens.every(token => `${hit.sectionLabel} ${hit.label} ${hit.keywords}`.toLocaleLowerCase().includes(token)))
}
