/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/ovispect/templates/**/*.html"],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
      },
      colors: {
        surface: '#141414',
        base: '#0a0a0a',
      },
    },
  },
  corePlugins: {
    preflight: true,
  },
};
