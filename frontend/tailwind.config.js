/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#08080c',
          raised: 'rgba(255,255,255,0.02)',
          hover: 'rgba(255,255,255,0.04)',
        },
        border: {
          DEFAULT: 'rgba(255,255,255,0.06)',
          hover: 'rgba(220,38,38,0.15)',
        },
        accent: {
          DEFAULT: '#DC2626',
          orange: '#EA580C',
          amber: '#F59E0B',
          blue: '#1D4ED8',
        },
        text: {
          primary: '#e4e4e7',
          secondary: '#9ca3af',
          muted: '#4b5563',
        },
      },
      fontFamily: {
        sans: [
          'SF Pro Display', 'SF Pro Text', '-apple-system', 'BlinkMacSystemFont',
          'system-ui', 'Segoe UI', 'Helvetica Neue', 'Arial', 'sans-serif',
        ],
        mono: [
          'SF Mono', 'Fira Code', 'Fira Mono', 'Roboto Mono', 'monospace',
        ],
      },
      borderRadius: {
        '2xl': '16px',
        '3xl': '24px',
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
