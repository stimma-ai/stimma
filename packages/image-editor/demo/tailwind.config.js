/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Stimma dark palette
        stimma: {
          bg: '#0f0f0f',
          surface: '#1a1a1a',
          canvas: '#0a0a0a',
        },
      },
    },
  },
  plugins: [],
};
