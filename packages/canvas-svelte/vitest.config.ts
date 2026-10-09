import { mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

// Component tests mount the browser runtime in jsdom.
export default mergeConfig(viteConfig, {
  resolve: { conditions: ['browser'] },
})
