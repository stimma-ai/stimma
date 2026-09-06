; Tauri's current-user NSIS bundles install directly under
; %LOCALAPPDATA%\<product name>. Keep that location for Electron so a
; Tauri-delivered Electron installer upgrades the existing application in
; place. This also keeps fresh installs and later electron-updater installs on
; one stable path.
; customInit runs after electron-builder's multi-user setup chooses the
; default %LOCALAPPDATA%\Programs path (and after it reads a previous Electron
; install location), so this assignment is the authoritative final location.
!macro customInit
  StrCpy $INSTDIR "$LOCALAPPDATA\${PRODUCT_NAME}"
!macroend

; Once the Electron payload and its own uninstaller are safely installed,
; remove the superseded Tauri installer entry and root-level sidecars. Leaving
; Tauri's uninstall.exe registered would be dangerous: invoking that stale
; entry later could delete the current Electron installation directory.
!macro customInstall
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
  Delete "$INSTDIR\uninstall.exe"
  Delete "$INSTDIR\stimma-watchdog.exe"
  RMDir /r "$INSTDIR\stimma-backend"

  ; Run the same hash verification, lock, temporary extraction, and atomic
  ; rename used by the normal launch fallback. The mode creates no window and
  ; exits as soon as the shared runtime is ready.
  DetailPrint "Preparing Python runtime..."
  ExecWait '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" --prepare-python-runtime' $0
  ${If} $0 != 0
    DetailPrint "Python runtime preparation failed with exit code $0; Stimma will retry on launch."
  ${EndIf}
!macroend
