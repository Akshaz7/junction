import { defineConfig } from '@playwright/test';
import base from '../../playwright.config';

// Keep the T-21 browser test inside the 3D worker's assigned folder.
export default defineConfig({
  ...base,
  testDir: '../..',
  testMatch: ['e2e/*.spec.ts', 'src/viewer3d/__e2e__/*.spec.ts'],
});
