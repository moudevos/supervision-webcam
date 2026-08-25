import { resolve } from "node:path";
import { defineConfig } from "vite";

const root = process.cwd();

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        camera: resolve(root, "index.html"),
        summary: resolve(root, "summary.html"),
        history: resolve(root, "history.html")
      }
    }
  }
});
