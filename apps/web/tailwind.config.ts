import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          900: "#0B0F17",
          800: "#141A24",
          700: "#1B2331",
        },
        brand: {
          indigo: "#6366F1",
          cyan: "#22D3EE",
        },
        muted: "#9AA5B8",
        success: "#34D399",
        warning: "#FBBF24",
        danger: "#F87171",
      },
      fontFamily: {
        sans: ["Noto Sans", "system-ui", "Segoe UI", "sans-serif"],
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(120deg, #6366F1 0%, #22D3EE 100%)",
        "glass-sheen":
          "linear-gradient(160deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.01) 100%)",
      },
      boxShadow: {
        glass: "0 12px 40px rgba(3, 7, 18, 0.55)",
        glow: "0 0 24px rgba(99, 102, 241, 0.35)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-ring": {
          "0%": { transform: "scale(0.9)", opacity: "0.7" },
          "100%": { transform: "scale(1.6)", opacity: "0" },
        },
      },
      animation: {
        "fade-up": "fade-up 260ms ease-out both",
        "pulse-ring": "pulse-ring 1.6s ease-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
