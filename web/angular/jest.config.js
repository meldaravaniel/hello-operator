/** @type {import('jest').Config} */
const config = {
  preset: 'jest-preset-angular',
  setupFilesAfterEnv: ['<rootDir>/setup-jest.ts'],
  testEnvironment: 'jsdom',
  transform: {
    '^.+\\.(ts|js|mjs|html|svg)$': [
      'jest-preset-angular',
      {
        tsconfig: '<rootDir>/tsconfig.spec.json',
        stringifyContentPathRegex: '\\.html$',
      },
    ],
  },
  // Resolve marked's CommonJS build to avoid ESM issues in Jest
  moduleNameMapper: {
    '^marked$': '<rootDir>/node_modules/marked/lib/marked.cjs',
  },
  testMatch: ['**/*.spec.ts'],
  collectCoverageFrom: ['src/app/**/*.ts', '!src/app/**/*.spec.ts'],
  coverageThreshold: {
    global: {
      branches: 60,
      functions: 60,
      lines: 60,
      statements: 60,
    },
  },
};

module.exports = config;
