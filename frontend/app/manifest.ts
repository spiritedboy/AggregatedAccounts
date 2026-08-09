import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Atlas Ledger · 多交易所资产",
    short_name: "Atlas Ledger",
    description: "只读的多交易所账户资产与收益聚合平台",
    start_url: "/dashboard",
    display: "standalone",
    background_color: "#0f1220",
    theme_color: "#7657F6",
    icons: [
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "maskable",
      },
    ],
  };
}
