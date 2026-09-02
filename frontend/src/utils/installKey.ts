/**
 * Keys scoped to THIS INSTALL and nothing else.
 *
 * Deliberately its own module with ZERO imports. Everything in storageKeys.ts
 * reaches for the bundle id, sandbox, profile or database guid, and since
 * multi-device those all describe whichever backend the window is DRIVING —
 * so a fact about the person sitting at this computer would change identity
 * the moment they pointed the window at another machine. Having no
 * dependencies is the guarantee, not an accident.
 *
 * Electron gives each install its own localStorage partition, so an
 * unqualified key is already install-scoped.
 *
 * Use for facts about the person or the machine, never for anything that
 * references a library: those belong in makeStorageKey/makeProfileKey.
 */
export function makeInstallKey(...parts: (string | number)[]): string {
  return `stimma_install_${parts.join('_')}`
}
