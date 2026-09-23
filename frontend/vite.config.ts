import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_BASE : "/mp3-audio-translator/" pour GitHub Pages (défini par le workflow), "/" en local.
export default defineConfig({
  base: process.env.VITE_BASE || "/",
  plugins: [react()],
  server: { port: 5173 },
});
