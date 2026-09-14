# Platform Study assets

Fixed surroundings only. The renderer adds the actual delivered platform icon
and app name locally. No demo checkout, network, image model or external font is
needed. No designer reference artwork is included.

- `android-home.png`: populated illustrative Samsung home screen. Native 512px
  Samsung and Google app artwork from their publisher listings on Google Play:
  Samsung Calendar, Clock, Notes, Health, Calculator, Voice Recorder, SmartThings,
  Email, Internet and My Files; Google Photos, Maps, Contacts, Phone and Messages.
  Their original alpha is retained; the Maps corner matte was removed. The
  changing app slot and label are blank. Layout is illustrative, not a stock
  installation screenshot. https://play.google.com/store/apps
- `android-studio.png` and `android-studio.json`: original procedural Galaxy-style
  phone geometry rendered once with Blender, with a calibrated screen mapping.
  The renderer adds the populated screen, punch-hole camera, icon and label locally.
- `galaxy.jpg`: original blank Galaxy S26 scene generated once with GPT Image,
  upscaled once with SeedVR2, stored at 3840 × 2560. Device geometry is illustrative.
- `macos.png`: native app artwork from Apple's Dock guide, with background pixels
  excluded from cutouts. Dock glass is composited onto Apple's Big Sur Coastline
  wallpaper. The app slot and tooltip are blank. Measured Dock proportions are
  rendered at 2×. https://support.apple.com/guide/imac/the-dock-apd4b7fb731f/mac
- `windows-start.png`: localized native pinned-app screenshot with one slot
  blanked. https://support.microsoft.com/en-us/windows/experience/personalization/customize-the-windows-start-menu
- `windows-taskbar.png`: localized composition using native taskbar app artwork
  and the same coastline wallpaper, with one app and tooltip blanked.
  https://support.microsoft.com/en-us/windows/experience/personalization/customize-the-taskbar-in-windows
- `ubuntu.png`: local 2× launcher rendering using native 512px Yaru icons by
  Ubuntu Yaru contributors (CC BY-SA 4.0; see YARU-LICENSE.txt), Mozilla's Firefox
  icon, and Canonical's Ubuntu 24.04 wallpaper. This adapted image retains
  CC BY-SA 4.0. No enlarged screenshot UI is used.
  https://github.com/ubuntu/yaru
  https://github.com/mozilla-firefox/firefox/blob/main/browser/branding/official/default256.png
  https://ubuntu.com/desktop/docs/en/24.04/tutorial/install-ubuntu-desktop/

- `kde.png`: illustrative Plasma floating-panel crop at 2× over an original
  geometric wallpaper. Native Breeze icons by KDE contributors: application
  launcher, Dolphin, web browser, Konsole, System Settings and Discover. The
  application slot and tooltip are blank. Source SVG artwork is available at
  https://invent.kde.org/frameworks/breeze-icons (icons/places/96/start-here-kde.svg,
  icons/apps/64/system-file-manager.svg and icons/apps/48/). See
  BREEZE-LICENSE.txt for LGPL-3.0-or-later and the artwork library clarification.
  Panel reference: https://kde.org/plasma-desktop/

Vendor artwork remains its respective owner's artwork. Dynamic labels use the
kit's bundled Noto Sans font. No proprietary font binary is redistributed.
