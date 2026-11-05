import type { MenuItemConstructorOptions } from 'electron'

export function applicationMenuTemplate(
  dev: boolean,
  platform: NodeJS.Platform,
  exportLogs: () => void,
): MenuItemConstructorOptions[] {
  const isMac = platform === 'darwin'
  const template: MenuItemConstructorOptions[] = isMac ? [
    { role: 'appMenu' },
    {
      label: 'File',
      submenu: [{ role: 'close' }],
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
  ] : []
  template.push({ role: 'help', submenu: [{ label: 'Export Logs…', click: exportLogs }] })
  return template
}
