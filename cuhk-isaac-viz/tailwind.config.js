/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Orbitron', 'sans-serif'],
        mono: ['Share Tech Mono', 'monospace'],
        audiowide: ['Audiowide', 'cursive'],
        rajdhani: ['Rajdhani', 'sans-serif'],
        cinzel: ['Cinzel', 'serif'],
        poiret: ['Poiret One', 'cursive'],
        philosopher: ['Philosopher', 'sans-serif'],
      },
      colors: {
        cuhk: {
          purple: '#7A003C',
          gold: '#D4AF37',
        },
        neon: {
          blue: '#00f3ff',
          pink: '#ff00ff',
        }
      },
      animation: {
        'spin-slow': 'spin 12s linear infinite',
        'pulse-fast': 'pulse 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float': 'float 6s ease-in-out infinite',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-20px)' },
        }
      }
    },
  },
  plugins: [],
}