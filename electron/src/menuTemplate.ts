import type { MenuItemConstructorOptions } from 'electron'

export function applicationMenuTemplate(
  dev: boolean,
  platform: NodeJS.Platform,
  exportLogs: () => void,
): MenuItemConstructorOptions[] | null {
  // Linux uses the in-app chrome; even a Help-only native menu takes a full row.
  // A null application menu removes the bar entirely, including Alt activation.
  if (platform === 'linux') return null

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
