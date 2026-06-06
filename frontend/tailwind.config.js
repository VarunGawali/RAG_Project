/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ey: {
          yellow:       '#FFE600',
          'yellow-dim': '#CCB800',
          dark:         '#2E2E38',
          darker:       '#1A1A24',
          surface:      '#23232F',
          card:         '#2E2E3A',
          'card-hover': '#353543',
          border:       '#3D3D50',
          muted:        '#747480',
          light:        '#C4C4CD',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        'fade-in':    'fadeIn 0.2s ease-out',
        'slide-in':   'slideIn 0.25s ease-out',
        'slide-up':   'slideUp 0.25s ease-out',
        'pulse-soft': 'pulseSoft 1.4s ease-in-out infinite',
      },
      keyframes: {
        fadeIn:     { from: { opacity: '0' },                          to: { opacity: '1' } },
        slideIn:    { from: { transform: 'translateX(100%)' },         to: { transform: 'translateX(0)' } },
        slideUp:    { from: { transform: 'translateY(8px)', opacity: '0' }, to: { transform: 'translateY(0)', opacity: '1' } },
        pulseSoft:  { '0%,100%': { opacity: '0.4' },                  '50%': { opacity: '1' } },
      },
    },
  },
  plugins: [],
}