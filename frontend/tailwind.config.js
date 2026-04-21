/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      screens: {
        phone: "375px",
        tablet: "768px",
        ipad: "1024px",
        web: "1280px",
        wide: "1440px",
      },
      colors: {
        kid: {
          primary: "#6C63FF",
          secondary: "#FF6B9D",
          accent: "#FFD93D",
          success: "#4CAF50",
          bg: "#F8F6FF",
        },
        parent: {
          primary: "#0F172A",
          accent: "#3B82F6",
          success: "#22C55E",
          warning: "#F59E0B",
          danger: "#EF4444",
          bg: "#FAFAFA",
          surface: "#FFFFFF",
          border: "#E5E7EB",
        },
        branch: {
          jump: "#6C63FF",
          spin: "#3B82F6",
          step: "#F59E0B",
          basic: "#22C55E",
          snowplow: "#EC4899",
        },
      },
      borderRadius: {
        "3xl": "24px",
        "4xl": "32px",
      },
      boxShadow: {
        soft: "0 18px 50px rgba(15, 23, 42, 0.08)",
        floating: "0 20px 60px rgba(59, 130, 246, 0.12)",
      },
      keyframes: {
        shimmer: {
          "0%": { transform: "translateX(-100%) skewX(-12deg)" },
          "100%": { transform: "translateX(400%) skewX(-12deg)" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-8px)" },
        },
        "unlock-pop": {
          "0%": { transform: "scale(0) rotate(-10deg)", opacity: "0" },
          "60%": { transform: "scale(1.2) rotate(5deg)", opacity: "1" },
          "100%": { transform: "scale(1) rotate(0deg)", opacity: "1" },
        },
      },
      animation: {
        shimmer: "shimmer 2s infinite",
        float: "float 2s ease-in-out infinite",
        "unlock-pop": "unlock-pop 0.5s cubic-bezier(0.34,1.56,0.64,1)",
      },
    },
  },
  plugins: []
};
