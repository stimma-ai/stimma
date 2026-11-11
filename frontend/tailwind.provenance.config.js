// Tailwind for the share page's provenance bundle (vite.provenance.config.js):
// the app's theme, only the provenance components as content, and no
// preflight — the bundle lives inside someone else's page.
import app from './tailwind.config.js'

export default {
  ...app,
  content: [
    './src/provenance/**/*.{vue,ts}',
    './src/components/ui/KeyValueList.vue',
    './src/components/ui/IconButton.vue',
    './src/components/ui/SegmentedControl.vue',
    './src/utils/promptSyntax.ts',
  ],
  corePlugins: { preflight: false },
  plugins: [],
}
