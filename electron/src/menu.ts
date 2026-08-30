/**
 * Application menu. Standard roles so platform shortcuts (Cmd-Q, Cmd-W,
 * Cmd-C/V/X, fullscreen, minimize) behave natively — the Tauri shell relied
 * on the default macOS menu for the same. Reload/DevTools are dev-only; the
 * packaged Tauri app exposed neither.
 */

import { Menu, MenuItemConstructorOptions, app } from 'electron'

export function installApplicationMenu(dev: boolean): void {
  const isMac = process.platform === 'darwin'

  const template: MenuItemConstructorOptions[] = [
    ...(isMac ? [{ role: 'appMenu' as const }] : []),
    {
      label: 'File',
      submenu: [isMac ? { role: 'close' as const } : { role: 'quit' as const }],
    },
    { role: 'editMenu' },
    {
      label: 'View',
      submenu: [
        ...(dev
          ? [
              { role: 'reload' as const },
              { role: 'forceReload' as const },
              { role: 'toggleDevTools' as const },
              { type: 'separator' as const },
            ]
          : []),
        // No zoom roles: the Tauri shell had no webview zoom accelerators.
        { role: 'togglefullscreen' as const },
      ],
    },
    { role: 'windowMenu' },
  ]

  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
  app.setName('Stimma')
}
