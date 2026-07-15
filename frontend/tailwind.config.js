/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'HarmonyOS Sans', 'Microsoft YaHei UI', 'system-ui', 'sans-serif'],
        display: ['Space Grotesk', 'Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        void: '#06070d',
        ink: '#0b0f19',
        panel: '#111827',
        cyan: '#38bdf8',
        violet: '#8b5cf6',
        gold: '#f4c76b',
        mint: '#22c55e',
        coral: '#fb7185',
      },
      boxShadow: {
        glow: '0 0 42px rgba(56, 189, 248, 0.22)',
        amber: '0 0 36px rgba(244, 199, 107, 0.18)',
      },
    },
  },
  plugins: [],
}
