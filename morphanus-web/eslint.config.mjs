import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  ...nextVitals,
  ...nextTypescript,
  {
    ignores: [".next/**", "node_modules/**"],
  },
  {
    rules: {
      "@next/next/no-img-element": "off",
    },
  },
];

export default config;
