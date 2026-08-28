import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["var(--font-ar)", "system-ui", "sans-serif"] },
      colors: {
        ink: { DEFAULT: "#1c1c1e", soft: "#3a3a3c", faint: "#8e8e93" },
        surface: { DEFAULT: "#ffffff", sunken: "#f2f2f7", raised: "#fbfbfd" },
        line: "#e5e5ea",
        ok: "#2f855a",
        warn: "#b7791f",
        stop: "#c53030",
      },
      borderRadius: { xl: "14px", "2xl": "20px" },
    },
  },
  plugins: [],
};
export default config;
