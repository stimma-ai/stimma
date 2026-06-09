/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['selector', '[data-theme="dark"]'],
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        base: 'var(--color-base)',
        surface: {
          DEFAULT: 'var(--color-surface)',
          raised: 'var(--color-surface-raised)',
          overlay: 'var(--color-surface-overlay)',
          hover: 'var(--color-surface-hover)',
          active: 'var(--color-surface-active)',
          elevated: 'var(--color-surface-elevated)',
        },
        slideshow: {
          matt: 'var(--color-slideshow-matt)',
        },
        content: {
          DEFAULT: 'var(--color-text-primary)',
          secondary: 'var(--color-text-secondary)',
          tertiary: 'var(--color-text-tertiary)',
          muted: 'var(--color-text-muted)',
        },
        edge: {
          DEFAULT: 'var(--color-border)',
          subtle: 'var(--color-border-subtle)',
          strong: 'var(--color-border-strong)',
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
        // Recipe graph node palette — refined matte colors for status, type
        // chips, and edges. See style.css for the per-theme values.
        recipe: {
          'done-tint':    'var(--color-recipe-done-tint)',
          'done-soft':    'var(--color-recipe-done-soft)',
          'done-strong':  'var(--color-recipe-done-strong)',
          'done-mid':     'var(--color-recipe-done-mid)',
          'run-tint':     'var(--color-recipe-run-tint)',
          'run-soft':     'var(--color-recipe-run-soft)',
          'run-strong':   'var(--color-recipe-run-strong)',
          'run-mid':      'var(--color-recipe-run-mid)',
          'fail-tint':    'var(--color-recipe-fail-tint)',
          'fail-soft':    'var(--color-recipe-fail-soft)',
          'fail-strong':  'var(--color-recipe-fail-strong)',
          'await-tint':   'var(--color-recipe-await-tint)',
          'await-soft':   'var(--color-recipe-await-soft)',
          'await-strong': 'var(--color-recipe-await-strong)',
          'stale-tint':   'var(--color-recipe-stale-tint)',
          'stale-soft':   'var(--color-recipe-stale-soft)',
          'stale-strong': 'var(--color-recipe-stale-strong)',
          'tool-tint':    'var(--color-recipe-type-tool-tint)',
          'tool-strong':  'var(--color-recipe-type-tool-strong)',
          'llm-tint':     'var(--color-recipe-type-llm-tint)',
          'llm-strong':   'var(--color-recipe-type-llm-strong)',
          'code-tint':    'var(--color-recipe-type-code-tint)',
          'code-strong':  'var(--color-recipe-type-code-strong)',
          'hitl-tint':    'var(--color-recipe-type-hitl-tint)',
          'hitl-strong':  'var(--color-recipe-type-hitl-strong)',
          'info-tint':    'var(--color-recipe-type-info-tint)',
          'info-strong':  'var(--color-recipe-type-info-strong)',
          'input-tint':   'var(--color-recipe-type-input-tint)',
          'input-strong': 'var(--color-recipe-type-input-strong)',
          'output-tint':  'var(--color-recipe-type-output-tint)',
          'output-strong':'var(--color-recipe-type-output-strong)',
          'control-tint': 'var(--color-recipe-type-control-tint)',
          'control-strong':'var(--color-recipe-type-control-strong)',
          'create-tint':  'var(--color-recipe-type-create-tint)',
          'create-strong':'var(--color-recipe-type-create-strong)',
        },
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
