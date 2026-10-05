/** @type {import("tailwindcss").Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      keyframes: {
        pulseRing: {
          "0%": { boxShadow: "0 0 0 0 rgba(220,38,38,0.55)" },
          "100%": { boxShadow: "0 0 0 12px rgba(220,38,38,0)" },
        },
      },
      animation: { "pulse-ring": "pulseRing 1.1s ease-out 3" },
    },
  },
  plugins: [],
};
