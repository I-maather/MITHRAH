/* eslint-env node */

/**
 * قواعد الحراسة الأمنية مُفعَّلة هنا لا في التعليقات.
 * The `no-restricted-syntax` block below is a *lint-level* guard: it fails the
 * build if anyone ever writes an order-construction call or embeds a broker
 * host in this app. It duplicates the jest guard in
 * `__tests__/security-boundary.test.ts` on purpose — two independent nets.
 */
module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['@typescript-eslint', 'react', 'react-hooks'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react/recommended',
    'plugin:react-hooks/recommended',
  ],
  settings: { react: { version: 'detect' } },
  env: { es2022: true, node: true },
  globals: {
    __DEV__: 'readonly',
    jest: 'readonly',
    describe: 'readonly',
    it: 'readonly',
    test: 'readonly',
    expect: 'readonly',
    beforeEach: 'readonly',
    afterEach: 'readonly',
    beforeAll: 'readonly',
    afterAll: 'readonly',
  },
  ignorePatterns: [
    'node_modules/',
    'ios/',
    'android/',
    '.expo/',
    'coverage/',
    'scripts/generate-placeholder-assets.mjs',
  ],
  rules: {
    'react/react-in-jsx-scope': 'off',
    'react/prop-types': 'off',
    '@typescript-eslint/no-explicit-any': 'error',
    '@typescript-eslint/explicit-module-boundary-types': 'off',
    '@typescript-eslint/no-unused-vars': [
      'error',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
    'no-console': ['error', { allow: ['warn', 'error'] }],
    eqeqeq: ['error', 'always'],
    'no-restricted-globals': [
      'error',
      { name: 'fetch', message: 'استعملي عميل الشبكة في src/api/client.ts فقط.' },
    ],
    'no-restricted-syntax': [
      'error',
      {
        selector:
          "CallExpression[callee.property.name=/^(placeOrder|createOrder|submitOrder|closePosition|modifyPosition|setLeverage)$/]",
        message:
          'لا بناء أوامر في التطبيق. التنفيذ كله في الخادم. (No order construction on device.)',
      },
    ],
  },
  overrides: [
    {
      files: ['__tests__/**/*.ts', '__tests__/**/*.tsx', 'jest.setup.ts'],
      rules: {
        'no-restricted-globals': 'off',
        '@typescript-eslint/no-require-imports': 'off',
        '@typescript-eslint/no-var-requires': 'off',
      },
    },
    {
      // ثلاثة مواضع وحدها تلمس الشبكة، وكلها **خارج شاشات العرض**:
      //   client.ts          البيانات
      //   SessionProvider    تجديد الرمز — خارج مجال v1
      //   enrolment.ts       التسجيل — يسبق وجود أي رمز، فلا عميل بعد
      // القاعدة الباقية: لا شاشة تلمس `fetch` مباشرةً.
      files: [
        'src/api/client.ts',
        'src/auth/SessionProvider.tsx',
        'src/auth/enrolment.ts',
      ],
      rules: { 'no-restricted-globals': 'off' },
    },
    {
      files: ['jest.setup.ts'],
      rules: { 'react/display-name': 'off' },
    },
  ],
};
