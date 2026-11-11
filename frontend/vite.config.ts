import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { PRODUCT_NAME } from "./src/brand";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["logo.svg"],
      workbox: {
        navigateFallback: "index.html",
        navigateFallbackDenylist: [/^\/api\//],
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith("/api/"),
            handler: "NetworkOnly",
          },
        ],
      },
      manifest: {
        name: PRODUCT_NAME,
        short_name: PRODUCT_NAME,
        description: "Rechnungen, Belege und DATEV-Export — ohne Schnickschnack.",
        lang: "de",
        start_url: "/",
        display: "standalone",
        background_color: "#f2f5f9",
        theme_color: "#004d9d",
        icons: [
          { src: "logo.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
          { src: "icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" }
        ]
      }
    })
  ],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000"
    }
  }
});
