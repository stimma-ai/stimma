/**
 * Application menu. Standard roles so platform shortcuts (Cmd-Q, Cmd-W,
 * Cmd-C/V/X, fullscreen, minimize) behave natively — the Tauri shell relied
 * on the default macOS menu for the same. Reload/DevTools are dev-only; the
 * packaged Tauri app exposed neither.
 */

import { Menu, app, dialog } from 'electron'
import { applicationMenuTemplate } from './menuTemplate.ts'
import { promptLogExport } from './logExport.ts'
import { getKnownDevices } from './devices.ts'
import { getProxyTarget } from './proxy.ts'

export function installApplicationMenu(dev: boolean, dataDir: string): void {
  app.setName('Stimma')
  const template = applicationMenuTemplate(dev, process.platform, () => {
    // Connection messages include roster names, route hosts and the proxy host.
    const identities = getKnownDevices().flatMap((device) => [device.name, ...device.routes.map((route) => route.host)])
    identities.push(getProxyTarget()?.host ?? '')
    void promptLogExport(dataDir, app.getVersion(), dialog, identities)
  })
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}
