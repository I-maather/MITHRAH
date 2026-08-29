/**
 * Path aliases (`@/*`) are resolved by Metro from `tsconfig.json` — Expo SDK 50+
 * enables `tsconfigPaths` in `expo/metro-config` by default — and by Jest from
 * `moduleNameMapper` in `jest.config.js`. No extra Babel resolver is needed.
 *
 * @type {(api: { cache: (v: boolean) => void }) => object}
 */
module.exports = function babelConfig(api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
  };
};
