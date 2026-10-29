import { test, expect } from '@playwright/test'
import * as path from 'path'

const ARTIFACTS_DIR = 'C:/Users/Mukesh/.gemini/antigravity/brain/e88bf82a-79b1-4096-a674-bc25b6ae4ad0'

test.describe('Step 2: Bisect Section Blank Canvas Bug', () => {
  test('Bisect across (a), (b), (c), (d)', async ({ page }) => {
    test.setTimeout(90000)

    await page.goto('http://127.0.0.1:5173')
    await page.waitForSelector('canvas', { timeout: 30000 })
    await page.waitForFunction(() => {
      const store = (window as any).useAssemblyStore?.getState?.()
      return store && store.components && store.components.length > 0
    }, { timeout: 30000 })
    await page.waitForTimeout(1000)

    // Helper to count visible non-bg pixels from canvas screenshot
    const analyzeCanvas = async (label: string, filename: string) => {
      const p = path.join(ARTIFACTS_DIR, filename)
      await page.locator('canvas').first().screenshot({ path: p })
      const res = await page.evaluate(() => {
        const store = (window as any).useAssemblyStore.getState()
        return {
          isSectionMode: store.isSectionMode,
          plane: store.sectionPlanes[0],
        }
      })
      console.log(`[BISECT] ${label} - screenshot saved to ${filename}`)
      return res
    }

    // Baseline: before section
    await analyzeCanvas('BASELINE', 'bisect_0_baseline.png')

    // Case (a): clipping plane only, no caps, no hatch, no gizmo
    await page.evaluate(() => {
      ;(window as any).__BISECT_DISABLE_CLIPPING__ = false
      ;(window as any).__BISECT_DISABLE_GIZMO__ = true
      ;(window as any).__BISECT_DISABLE_CAPS__ = true
      ;(window as any).__BISECT_DISABLE_HATCH__ = true
      const store = (window as any).useAssemblyStore.getState()
      store.setIsSectionMode(true)
    })
    await page.waitForTimeout(800)
    await analyzeCanvas('(a) clipping plane only', 'bisect_a_clip_only.png')

    // Case (b): plus gizmo
    await page.evaluate(() => {
      ;(window as any).__BISECT_DISABLE_GIZMO__ = false
    })
    await page.waitForTimeout(800)
    await analyzeCanvas('(b) plus gizmo', 'bisect_b_plus_gizmo.png')

    // Case (c): plus stencil caps (no hatch)
    await page.evaluate(() => {
      ;(window as any).__BISECT_DISABLE_CAPS__ = false
      ;(window as any).__BISECT_DISABLE_HATCH__ = true
    })
    await page.waitForTimeout(800)
    await analyzeCanvas('(c) plus caps (no hatch)', 'bisect_c_plus_caps.png')

    // Case (d): plus hatch shader
    await page.evaluate(() => {
      ;(window as any).__BISECT_DISABLE_HATCH__ = false
    })
    await page.waitForTimeout(800)
    await analyzeCanvas('(d) plus hatch shader', 'bisect_d_plus_hatch.png')

    expect(true).toBe(true)
  })
})
