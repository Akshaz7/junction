import { defineConfig, mergeConfig } from 'vite'
import base from '../vite.config'
// Worktree-local dependency cache: node_modules is shared with the other workers.
export default defineConfig((env) => mergeConfig(base(env), { cacheDir: '.cache/markup-vite' }))
