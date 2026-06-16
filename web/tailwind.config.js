/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#06111f",
        panel: "#0d1b2f",
        cyanGlow: "#22d3ee"
      },
      boxShadow: {
        glow: "0 0 40px rgba(34, 211, 238, 0.16)"
      }
    }
  },
  plugins: []
};
