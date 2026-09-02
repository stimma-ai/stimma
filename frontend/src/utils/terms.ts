/**
 * Terms-of-service acceptance.
 *
 * Agreeing to the terms is a fact about the person at this computer, not about
 * the library they happen to be looking at. Every other first-run flag is
 * namespaced by bundle id and sandbox, and since multi-device those come from
 * the backend the window is DRIVING — so pointing the window at a second
 * computer made the clickwrap reappear and asked the same person to agree all
 * over again. This one key is install-scoped instead.
 *
 * The rest of onboarding stays per-backend on purpose: providers, profiles and
 * readiness really are properties of the machine being set up.
 */
import { makeInstallKey } from './installKey.ts'

/** Bump when the terms themselves change, to ask once more. */
export const TERMS_VERSION = 1

/**
 * The version in force back when finishing onboarding WAS the clickwrap, and
 * there was no key of our own. Adopted rather than TERMS_VERSION so a future
 * bump still asks those users, instead of silently agreeing on their behalf.
 */
const LEGACY_VERSION = 1

const KEY = makeInstallKey('terms_accepted')

interface Acceptance {
  version: number
  at: string
}

function read(): Acceptance | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (typeof parsed?.version !== 'number') return null
    return parsed as Acceptance
  } catch {
    // Unreadable or hand-edited: treat as never accepted and ask again, which
    // is the safe direction for a clickwrap.
    return null
  }
}

/** Has the person at this computer accepted the terms as they stand now? */
export function hasAcceptedTerms(): boolean {
  const accepted = read()
  return accepted !== null && accepted.version >= TERMS_VERSION
}

function write(version: number): void {
  try {
    localStorage.setItem(
      KEY,
      JSON.stringify({ version, at: new Date().toISOString() } satisfies Acceptance),
    )
  } catch {
    // Private mode or a full quota: the clickwrap simply shows again.
  }
}

export function recordTermsAcceptance(): void {
  write(TERMS_VERSION)
}

/**
 * Treat an already-finished onboarding as the acceptance it was.
 *
 * Everyone who onboarded before this key existed agreed to the terms then —
 * that sentence was the whole point of the footer. Without this they would be
 * asked exactly once more, the first time they point the window at another
 * server, which is the thing being fixed. Runs once, only when there is no
 * record at all.
 */
export function adoptLegacyAcceptance(onboardingCompleted: boolean): void {
  if (!onboardingCompleted) return
  if (read() !== null) return
  write(LEGACY_VERSION)
}

/** Developer "reset onboarding" only — a real first run includes the terms. */
export function clearTermsAcceptance(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // Nothing to do.
  }
}
