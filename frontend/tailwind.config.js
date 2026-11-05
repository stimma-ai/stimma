/** @type {import('tailwindcss').Config} */
// Shadow ink at a theme-scaled opacity (see --shadow-*-a in style.css).
const ink = (alpha, tier) => `rgb(0 0 0 / calc(${alpha} * var(--shadow-${tier}-a)))`
export default {
  // Hover styles only where the primary pointer can hover. On a phone the
  // first tap would otherwise "hover" a tile (revealing its checkbox) and
  // iOS Safari withholds the click until a second tap.
  future: { hoverOnlyWhenSupported: true },
  darkMode: ['selector', '[data-theme="dark"]'],
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    borderRadius: {
      none: '0',
      sm: 'var(--radius-sm)',
      DEFAULT: 'var(--radius-sm)',
      md: 'var(--radius-md)',
      lg: 'var(--radius-lg)',
      xl: 'var(--radius-lg)',
      '2xl': 'var(--radius-lg)',
      '3xl': 'var(--radius-lg)',
      full: 'var(--radius-full)',
      // Atelier: media tiles/viewers only — the artwork stays square.
      media: 'var(--radius-media)',
    },
    extend: {
      fontFamily: {
        // Stimma logotype font (self-hosted, see @font-face in style.css).
        // Always use `font-brand` for the wordmark so the fallback stack
        // applies — a bare font-family with no fallback degrades to serif.
        brand: ['General Sans', 'system-ui', 'sans-serif'],
      },
      // shadow-black/NN is the app's one "ink" shadow color; scale it with the
      // theme like the shadow scale so a light page isn't dragged down by it.
      boxShadowColor: {
        black: ({ opacityValue }) =>
          `rgb(0 0 0 / calc(${opacityValue === undefined ? 1 : opacityValue} * var(--shadow-pop-a)))`,
      },
      // Page rhythm and icon scale tokens (style.css). `px-page`, `-mx-page`,
      // `gap-section`, `space-y-section`, `w-icon-nav` and friends.
      spacing: {
        page: 'var(--page-margin)',
        section: 'var(--section-gap)',
        'header-pb': 'var(--header-pb)',
        'icon-inline': 'var(--icon-inline)',
        'icon-nav': 'var(--icon-nav)',
        'icon-canvas': 'var(--icon-canvas)',
      },
      height: {
        control: 'var(--control-h)',
        'control-main': 'var(--control-h-main)',
        header: 'var(--header-h)',
        'header-compact': 'var(--header-h-compact)',
        'header-mobile': 'var(--header-h-mobile)',
      },
      minHeight: {
        control: 'var(--control-h)',
        'control-main': 'var(--control-h-main)',
        header: 'var(--header-h)',
        'header-compact': 'var(--header-h-compact)',
        'header-mobile': 'var(--header-h-mobile)',
      },
      // Dense-control tier: actionable labels in tool, flow and editor forms.
      // Between text-xs (12/16) and text-sm (14/20); mono facts stay text-xs.
      fontSize: {
        ctl: ['13px', { lineHeight: '18px' }],
        // Compact transcript reading tier: long assistant text on a phone.
        // 16px at 1.5; facts and controls keep their dense tiers. The
        // matching `prose-read` size below types markdown to the same measure.
        read: ['16px', { lineHeight: '1.5' }],
      },
      colors: {
        // Solid tokens are stored as RGB channels in style.css so the
        // `<alpha-value>` placeholder lets opacity modifiers work, e.g.
        // `bg-surface/50`, `border-edge/30`. rgba-based tokens (edge.subtle,
        // surface.elevated, the overlay scale) can't take a further opacity
        // modifier — use the dedicated faintness tokens instead of `/NN`.
        base: 'rgb(var(--color-base-rgb) / <alpha-value>)',
        surface: {
          DEFAULT: 'rgb(var(--color-surface-rgb) / <alpha-value>)',
          raised: 'rgb(var(--color-surface-raised-rgb) / <alpha-value>)',
          overlay: 'rgb(var(--color-surface-overlay-rgb) / <alpha-value>)',
          hover: 'rgb(var(--color-surface-hover-rgb) / <alpha-value>)',
          active: 'rgb(var(--color-surface-active-rgb) / <alpha-value>)',
          elevated: 'var(--color-surface-elevated)',
        },
        slideshow: {
          matt: 'var(--color-slideshow-matt)',
        },
        // Atelier accents. accent = THE interactive accent (fills);
        // accent-hi = brightened variant for text/icons/rings on dark;
        // selection = selected-state indigo (selection ≠ action);
        // matte = media matte behind tiles/viewers.
        accent: {
          DEFAULT: 'rgb(var(--color-accent-rgb) / <alpha-value>)',
          hi: 'rgb(var(--color-accent-hi-rgb) / <alpha-value>)',
          // Label/glyph colour ON an accent fill (>= 4.5:1 in both themes).
          on: 'rgb(var(--color-on-accent-rgb) / <alpha-value>)',
        },
        selection: 'rgb(var(--color-selection-rgb) / <alpha-value>)',
        // live = autonomous/continuous operation states (forever mode,
        // transport toggles). Fun on purpose; never a resting control.
        live: 'rgb(var(--color-live-rgb) / <alpha-value>)',
        // Destructive/error foreground. Light theme deepens it; red-500/600
        // fills are untouched.
        red: { 400: 'rgb(var(--color-danger-fg-rgb) / <alpha-value>)' },
        matte: 'rgb(var(--color-matte-rgb) / <alpha-value>)',
        content: {
          DEFAULT: 'rgb(var(--color-text-primary-rgb) / <alpha-value>)',
          secondary: 'rgb(var(--color-text-secondary-rgb) / <alpha-value>)',
          tertiary: 'rgb(var(--color-text-tertiary-rgb) / <alpha-value>)',
          muted: 'rgb(var(--color-text-muted-rgb) / <alpha-value>)',
        },
        edge: {
          DEFAULT: 'rgb(var(--color-border-rgb) / <alpha-value>)',
          subtle: 'var(--color-border-subtle)',
          strong: 'rgb(var(--color-border-strong-rgb) / <alpha-value>)',
        },
        overlay: {
          faint: 'var(--color-overlay-faint)',
          subtle: 'var(--color-overlay-subtle)',
          hover: 'var(--color-overlay-hover)',
          light: 'var(--color-overlay-light)',
          medium: 'var(--color-overlay-medium)',
          strong: 'var(--color-overlay-strong)',
          backdrop: 'var(--color-backdrop)',
        },
        // Text fields and the composer: fill-only, one small step above the surface.
        field: 'var(--color-field)',
        // Flow graph node palette — refined matte colors for status, type
        // chips, and edges. See style.css for the per-theme values.
        flow: {
          'done-tint':    'var(--color-flow-done-tint)',
          'done-soft':    'var(--color-flow-done-soft)',
          'done-strong':  'var(--color-flow-done-strong)',
          'done-mid':     'var(--color-flow-done-mid)',
          'run-tint':     'var(--color-flow-run-tint)',
          'run-soft':     'var(--color-flow-run-soft)',
          'run-strong':   'var(--color-flow-run-strong)',
          'run-mid':      'var(--color-flow-run-mid)',
          'fail-tint':    'var(--color-flow-fail-tint)',
          'fail-soft':    'var(--color-flow-fail-soft)',
          'fail-strong':  'var(--color-flow-fail-strong)',
          'await-tint':   'var(--color-flow-await-tint)',
          'await-soft':   'var(--color-flow-await-soft)',
          'await-strong': 'var(--color-flow-await-strong)',
          'stale-tint':   'var(--color-flow-stale-tint)',
          'stale-soft':   'var(--color-flow-stale-soft)',
          'stale-strong': 'var(--color-flow-stale-strong)',
          'tool-tint':    'var(--color-flow-type-tool-tint)',
          'tool-strong':  'var(--color-flow-type-tool-strong)',
          'llm-tint':     'var(--color-flow-type-llm-tint)',
          'llm-strong':   'var(--color-flow-type-llm-strong)',
          'code-tint':    'var(--color-flow-type-code-tint)',
          'code-strong':  'var(--color-flow-type-code-strong)',
          'hitl-tint':    'var(--color-flow-type-hitl-tint)',
          'hitl-strong':  'var(--color-flow-type-hitl-strong)',
          'info-tint':    'var(--color-flow-type-info-tint)',
          'info-strong':  'var(--color-flow-type-info-strong)',
          'input-tint':   'var(--color-flow-type-input-tint)',
          'input-strong': 'var(--color-flow-type-input-strong)',
          'output-tint':  'var(--color-flow-type-output-tint)',
          'output-strong':'var(--color-flow-type-output-strong)',
          'control-tint': 'var(--color-flow-type-control-tint)',
          'control-strong':'var(--color-flow-type-control-strong)',
          'create-tint':  'var(--color-flow-type-create-tint)',
          'create-strong':'var(--color-flow-type-create-strong)',
        },
      },
      // Elevation tokens: tighter than Tailwind's defaults (less spread), with
      // opacity scaled by the per-theme --shadow-*-a vars in style.css (light is
      // much softer). Literal lengths keep shadow-<color> utilities working.
      boxShadow: {
        sm: `0 1px 2px 0 ${ink(0.05, 'page')}`,
        DEFAULT: `0 1px 3px 0 ${ink(0.1, 'page')}, 0 1px 2px -1px ${ink(0.1, 'page')}`,
        md: `0 4px 6px -1px ${ink(0.1, 'page')}, 0 2px 4px -2px ${ink(0.1, 'page')}`,
        lg: `0 8px 12px -4px ${ink(0.1, 'pop')}, 0 3px 5px -3px ${ink(0.1, 'pop')}`,
        xl: `0 14px 20px -6px ${ink(0.1, 'pop')}, 0 6px 8px -5px ${ink(0.1, 'pop')}`,
        '2xl': `0 20px 40px -12px ${ink(0.25, 'pop')}`,
      },
      // Atelier z-scale — the ONLY sanctioned z-index values. Arbitrary
      // z-[NNNN] is banned in new code; migrate stragglers onto these tiers.
      zIndex: {
        chrome: '30',    // sticky headers, in-page floating chrome
        overlay: '50',   // full-screen in-app viewers (slideshow, compare) —
                         // above chrome, below teleported menus/modals/toasts
        modal: '200',    // modal dialogs + their backdrops
        confirm: '210',  // confirm launched from within a modal
        menu: '220',     // context menus, dropdowns, popovers, pickers, tooltips.
                         // ABOVE modals: menus teleport to body, so they compete
                         // with modals in the root stacking context — and a menu
                         // opened from inside a modal must paint over it. Safe
                         // because menus are transient and close on any outside
                         // interaction.
        submenu: '230',  // hover submenus of the above
        toast: '300',    // toasts
        top: '400',      // boot/first-run overlays only
      },
      // Soft pulse for "your turn" status dots — Tailwind's built-in
      // `animate-pulse` (50% opacity dip) is too aggressive for a 10px
      // chip-sized dot; this version stays closer to full opacity.
      keyframes: {
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.55' },
        },
        // Travelling sheen for an indeterminate progress segment — honest
        // "working, position unknown", unlike a bar parked at a fixed width.
        'shimmer': {
          '0%':   { backgroundPosition: '150% 0' },
          '100%': { backgroundPosition: '-150% 0' },
        },
      },
      animation: {
        'pulse-soft': 'pulse-soft 1.8s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'shimmer': 'shimmer 2.2s linear infinite',
      },
      typography: {
        DEFAULT: {
          css: {
            '--tw-prose-body': 'var(--color-text-primary)',
            '--tw-prose-headings': 'var(--color-text-primary)',
            '--tw-prose-links': 'var(--color-text-primary)',
            '--tw-prose-bold': 'var(--color-text-primary)',
            '--tw-prose-counters': 'var(--color-text-secondary)',
            '--tw-prose-bullets': 'var(--color-text-muted)',
            '--tw-prose-hr': 'var(--color-border)',
            '--tw-prose-quotes': 'var(--color-text-secondary)',
            '--tw-prose-quote-borders': 'var(--color-border)',
            '--tw-prose-captions': 'var(--color-text-muted)',
            '--tw-prose-code': 'var(--color-text-primary)',
            '--tw-prose-pre-code': 'var(--color-text-primary)',
            '--tw-prose-pre-bg': 'var(--color-base)',
            '--tw-prose-th-borders': 'var(--color-border)',
            '--tw-prose-td-borders': 'var(--color-border-subtle)',
            'code': {
              backgroundColor: 'var(--color-surface)',
              padding: '0.2em 0.4em',
              borderRadius: '0.25rem',
            },
            'th': {
              backgroundColor: 'var(--color-surface)',
            },
          },
        },
        // `prose-read`: the compact transcript size (use as `compact:prose-read`).
        // 16px / 1.5, tighter block spacing, and lists indented one step instead
        // of the default 1.6em so the reading area stays wide.
        read: {
          css: {
            fontSize: '1rem',
            lineHeight: '1.5',
            p: { marginTop: '0.75em', marginBottom: '0.75em' },
            'ul, ol': { marginTop: '0.75em', marginBottom: '0.75em', paddingInlineStart: '1.25em' },
            li: { marginTop: '0.25em', marginBottom: '0.25em' },
            'ol > li, ul > li': { paddingInlineStart: '0.25em' },
            'li > p, li > ul, li > ol': { marginTop: '0.25em', marginBottom: '0.25em' },
            h1: { fontSize: '1.375em', marginTop: '1em', marginBottom: '0.5em', lineHeight: '1.25' },
            h2: { fontSize: '1.25em', marginTop: '1em', marginBottom: '0.5em', lineHeight: '1.3' },
            h3: { fontSize: '1.125em', marginTop: '1em', marginBottom: '0.4em', lineHeight: '1.4' },
            h4: { marginTop: '1em', marginBottom: '0.4em', lineHeight: '1.5' },
            code: { fontSize: '0.875em' },
            'pre code': { fontSize: '0.8125em' },
            pre: { marginTop: '0.75em', marginBottom: '0.75em', paddingInline: '0.75em', fontSize: '0.875em' },
            blockquote: { marginTop: '0.75em', marginBottom: '0.75em', paddingInlineStart: '0.75em' },
          },
        },
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
    require('@tailwindcss/container-queries'),
    // Viewport variants bound to useViewport.ts (DESIGN.md §1.11), not to raw
    // media queries, so the dev/test override (?viewport=compact) and the
    // chrome agree. `compact:` = phone chrome (< 768px or a native phone
    // shell); `coarse:` = touch pointer. `narrow:` / `medium:` / `wide:` are
    // the live width band (< 600 / 600–839 / ≥ 840), and `roomy:` is compact
    // chrome with a medium-or-wider window: an unfolded foldable.
    function ({ addVariant }) {
      addVariant('compact', '[data-viewport="compact"] &')
      addVariant('not-compact', '[data-viewport]:not([data-viewport="compact"]) &')
      addVariant('coarse', '[data-pointer="coarse"] &')
      addVariant('narrow', '[data-width="narrow"] &')
      addVariant('medium', '[data-width="medium"] &')
      addVariant('wide', '[data-width="wide"] &')
      addVariant('roomy', '[data-viewport="compact"]:not([data-width="narrow"]) &')
    },
  ],
}
