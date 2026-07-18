/** @type {import('tailwindcss').Config} */
export default {
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
        },
        selection: 'rgb(var(--color-selection-rgb) / <alpha-value>)',
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
      // Atelier z-scale — the ONLY sanctioned z-index values. Arbitrary
      // z-[NNNN] is banned in new code; migrate stragglers onto these tiers.
      zIndex: {
        chrome: '30',    // sticky headers, in-page floating chrome
        menu: '100',     // context menus, dropdowns, popovers, pickers
        submenu: '110',  // hover submenus of the above
        modal: '200',    // modal dialogs + their backdrops
        confirm: '210',  // confirm launched from within a modal
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
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
}
