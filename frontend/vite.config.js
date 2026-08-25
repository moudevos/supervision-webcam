import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        camera: resolve(__dirname, "index.html"),
        summary: resolve(__dirname, "summary.html"),
        history: resolve(__dirname, "history.html")
      }
    }
  }
});
