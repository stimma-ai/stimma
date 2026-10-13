// The share page's "How it was made" panel as a standalone bundle:
//
//   npm run build:provenance-view
//   → dist-provenance/provenance-view.js    IIFE, Vue bundled, window.StimmaProvenance
//     dist-provenance/provenance-view.css   Tailwind (app config + tokens, dark and
//                                           light), no preflight, all under .stimma-pv
//     dist-provenance/build-info.json       { commit, builtAt }
//
// The bundle is the same components the app renders its history with
// (src/provenance). It must never pull in app plumbing; `pureTree` fails the
// build if anything that talks to the backend, the router or the stores
// sneaks into its import graph.
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import postcss from 'postcss'
import tailwindcss from 'tailwindcss'
import autoprefixer from 'autoprefixer'
import { execSync } from 'child_process'
import { readFileSync, writeFileSync } from 'fs'
import { resolve } from 'path'
import { fileURLToPath } from 'url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const OUT_DIR = resolve(__dirname, 'dist-provenance')
const SCOPE = '.stimma-pv'

const FORBIDDEN = [
  /\/node_modules\/axios\//,
  /\/src\/apiConfig/,
  /\/src\/router/,
  /\/src\/stores?\//,
  /\/src\/composables\//,
  /\/src\/desktop\//,
  /\/src\/views\//,
  /\/MediaImage\.vue/,
  /\/AppImage\.vue/,
]

function pureTree() {
  return {
    name: 'provenance-pure-tree',
    load(id) {
      const path = id.split('?')[0]
      const hit = FORBIDDEN.find(re => re.test(path))
      if (hit) this.error(`provenance bundle must not import ${path.replace(__dirname, '')} (matched ${hit})`)
      return null
    },
  }
}

/** Tokens the panel's utilities can reach: colors (minus flow/lineage palettes) and radii. */
function isPanelToken(prop) {
  if (prop === 'color-scheme' || prop.startsWith('--radius-')) return true
  return prop.startsWith('--color-') && !/^--color-(flow|lineage|scrollbar)-/.test(prop)
}

/** The theme tokens from src/style.css, scoped: `@stimma-provenance-tokens;` → rules. */
function themeTokens() {
  return {
    postcssPlugin: 'stimma-provenance-tokens',
    AtRule: {
      'stimma-provenance-tokens': (atRule) => {
        const app = postcss.parse(readFileSync(resolve(__dirname, 'src/style.css'), 'utf8'))
        const out = []
        app.walkRules((rule) => {
          if (rule.parent.type !== 'root') return
          const theme = rule.selector.match(/^\[data-theme="(dark|light)"\]$/)
          if (!theme && rule.selector !== ':root') return
          const decls = rule.nodes.filter(n => n.type === 'decl' && isPanelToken(n.prop))
          if (!decls.length) return
          out.push(postcss.rule({
            selector: theme ? `${SCOPE} [data-theme="${theme[1]}"]` : `${SCOPE} [data-theme]`,
            nodes: decls.map(d => d.clone()),
          }))
        })
        // :root carries the theme-independent scale (radii); it must come first.
        out.sort((a, b) => (a.selector.endsWith('[data-theme]') ? -1 : 0) - (b.selector.endsWith('[data-theme]') ? -1 : 0))
        atRule.replaceWith(out)
      },
    },
  }
}
themeTokens.postcss = true

/** Every rule under `.stimma-pv`; rem → px so the host page's root size can't rescale the panel. */
function scope() {
  return {
    postcssPlugin: 'stimma-provenance-scope',
    Rule(rule) {
      if (rule.parent?.type === 'atrule' && /keyframes$/i.test(rule.parent.name)) return
      if (rule.selector.startsWith(SCOPE)) return
      rule.selectors = rule.selectors.map(sel => (sel.startsWith(SCOPE) ? sel : `${SCOPE} ${sel}`))
    },
    Declaration(decl) {
      if (/\d*\.?\d+rem\b/.test(decl.value)) {
        decl.value = decl.value.replace(/(-?\d*\.?\d+)rem\b/g, (_, n) => `${parseFloat((Number(n) * 16).toFixed(3))}px`)
      }
    },
  }
}
scope.postcss = true

function buildInfo() {
  return {
    name: 'provenance-build-info',
    closeBundle() {
      let commit = ''
      try {
        commit = execSync('git rev-parse HEAD', { cwd: __dirname }).toString().trim()
      } catch {
        // not a git checkout
      }
      writeFileSync(resolve(OUT_DIR, 'build-info.json'), `${JSON.stringify({ commit, builtAt: new Date().toISOString() }, null, 2)}\n`)
    },
  }
}

export default defineConfig({
  plugins: [pureTree(), vue(), buildInfo()],
  publicDir: false,
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
    __VUE_OPTIONS_API__: 'false',
    __VUE_PROD_DEVTOOLS__: 'false',
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: 'false',
  },
  css: {
    postcss: {
      plugins: [
        themeTokens(),
        tailwindcss({ config: resolve(__dirname, 'tailwind.provenance.config.js') }),
        autoprefixer(),
        scope(),
      ],
    },
  },
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    copyPublicDir: false,
    lib: {
      entry: resolve(__dirname, 'src/provenance/standalone/index.ts'),
      formats: ['iife'],
      name: 'StimmaProvenance',
      fileName: () => 'provenance-view.js',
      cssFileName: 'provenance-view',
    },
  },
})
