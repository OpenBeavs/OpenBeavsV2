module.exports = {
  root: true,
  env: { browser: true, node: true, es2022: true },
  extends: ['eslint:recommended', 'plugin:@typescript-eslint/recommended', 'plugin:svelte/recommended'],
  parser: '@typescript-eslint/parser',
  parserOptions: { sourceType: 'module', ecmaVersion: 2022, extraFileExtensions: ['.svelte'] },
  overrides: [{ files: ['*.svelte'], parser: 'svelte-eslint-parser', parserOptions: { parser: '@typescript-eslint/parser' } }],
  ignorePatterns: ['build/', '.svelte-kit/', 'node_modules/', 'playwright-report/', 'test-results/']
};
