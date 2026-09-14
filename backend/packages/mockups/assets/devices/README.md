# Device scene assets

These assets are shared by all app-icons runs that include iOS. Recipe rendering
uses local Pillow/NumPy transforms and the bundled Noto Sans font for the changing
app label. No model call, font download, Blender installation or device connection
is required. Long labels are truncated within their home-screen slot.

- `ios-home.png`: an iOS 18.4 context composition with the changing app slot blank.
  Neighboring icons and system indicators come from simulator captures. Static
  labels were rasterized using SF Pro; no Apple font binary is redistributed.
  The Calendar tile preserves the captured September 14 date. Native icon
  cutouts exclude the source wallpaper at their antialiased edges; the app slot
  and static labels remain separate from those masks.
- `studio.png`: original procedural phone geometry and lighting rendered once in
  Blender, with a blank screen and transparent surroundings. This is illustrative
  geometry, not an official Apple product render.
- `cafe.jpg`: original empty-phone photograph generated using GPT Image, upscaled
  once using SeedVR2 7B to 3840 × 2560, then stored at JPEG quality 97 without
  chroma subsampling. App artwork and labels are composited afterward and never
  pass through either model.
- The JSON files store screen corners clockwise from top left and plate dimensions.

Apple artwork remains Apple's artwork; it is not part of an original icon library.
Apple design resources: https://developer.apple.com/design/resources/
The scenes do not incorporate the supplied designer reference artwork or photos.
They are context mockups, not screenshots of an installed application.
