/**
 * Target languages offered by the prompt editor's Translate control.
 *
 * `code` is the stable key persisted in promptOptions.translate.language.
 * `label` is the native display name shown in the menu.
 * `english` is the human-readable name sent to the backend translator (the LLM
 * prompt is phrased in English, e.g. "translate into Simplified Chinese").
 *
 * Scope: Chinese first (the priority), then mainstream European languages,
 * English (for users typing in another language), plus Japanese & Korean.
 */
export interface PromptLanguage {
  code: string
  label: string
  english: string
}

export const PROMPT_LANGUAGES: PromptLanguage[] = [
  { code: 'zh-Hans', label: '简体中文', english: 'Simplified Chinese' },
  { code: 'zh-Hant', label: '繁體中文', english: 'Traditional Chinese' },
  { code: 'en', label: 'English', english: 'English' },
  { code: 'es', label: 'Español', english: 'Spanish' },
  { code: 'fr', label: 'Français', english: 'French' },
  { code: 'de', label: 'Deutsch', english: 'German' },
  { code: 'it', label: 'Italiano', english: 'Italian' },
  { code: 'pt', label: 'Português', english: 'Portuguese' },
  { code: 'ja', label: '日本語', english: 'Japanese' },
  { code: 'ko', label: '한국어', english: 'Korean' },
]

/** Default target when Translate is first switched on. */
export const DEFAULT_TRANSLATE_LANGUAGE = 'zh-Hans'

export function promptLanguageByCode(code: string | null | undefined): PromptLanguage | undefined {
  if (!code) return undefined
  return PROMPT_LANGUAGES.find((l) => l.code === code)
}
