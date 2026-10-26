import prettier from 'eslint-config-prettier';

import apify from '@apify/eslint-config/js.js';

export default [
    {
        ignores: ['**/dist', '**/coverage', 'eslint.config.mjs', 'check-playwright-version.mjs'],
    },
    ...apify,
    prettier,
];
