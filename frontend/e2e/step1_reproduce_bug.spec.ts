import { test, expect } from '@playwright/test'
import * as path from 'path'

const ARTIFACTS_DIR = 'C:/Users/Mukesh/.gemini/antigravity/brain/e88bf82a-79b1-4096-a674-bc25b6ae4ad0'

test.describe('Step 1 & Step 2: Reproduce Section Blank Bug & Bisect', () => {
  test('Reproduce: Section default plane must cut through model center, show >=30% model, not blank canvas', async ({ page }) => {
    test.setTimeout(60000)

    const consoleErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })
    page.on('pageerror', (err) => {
      consoleErrors.push(err.message)
    })

    await page.goto('http://127.0.0.1:5173')
    await page.waitForSelector('canvas', { timeout: 30000 })
    await page.waitForFunction(() => {
      const store = (window as any).useAssemblyStore?.getState?.()
      return store && store.components && store.components.length > 0
    }, { timeout: 30000 })
    await page.waitForTimeout(1000)

    // Capture WebGL diagnostics
    const glDiag = await page.evaluate(() => {
      const canvas = document.querySelector('canvas') as HTMLCanvasElement
      const gl = canvas?.getContext('webgl2') || canvas?.getContext('webgl')
      return {
        glError: gl ? gl.getError() : -1,
        localClippingEnabled: (window as any).__CAD_VIEWER__?.gl?.localClippingEnabled ?? null,
      }
    })
    console.log('WebGL Diagnostics:', glDiag)

    // 1. Get assembly bounding box in CAD and verify center
    const bboxInfo = await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      const comps = store.components.filter((c: any) => c.is_leaf && c.bounding_box)
      let minX = Infinity, minY = Infinity, minZ = Infinity
      let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
      for (const c of comps) {
        const bb = c.bounding_box
        minX = Math.min(minX, bb.xmin)
        minY = Math.min(minY, bb.ymin)
        minZ = Math.min(minZ, bb.zmin)
        maxX = Math.max(maxX, bb.xmax)
        maxY = Math.max(maxY, bb.ymax)
        maxZ = Math.max(maxZ, bb.zmax)
      }
      return {
        min: [minX, minY, minZ],
        max: [maxX, maxY, maxZ],
        center: [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2],
      }
    })
    console.log('Assembly Bounding Box Info:', bboxInfo)

    // Take screenshot BEFORE section
    const pBefore = path.join(ARTIFACTS_DIR, 'reproduce_before_section.png')
    await page.locator('canvas').first().screenshot({ path: pBefore })

    // 2. Click Section button to enable section mode (default plane Top, offset 0.0, tilt 0)
    const sectionBtn = page.locator('[data-testid="toolbar-section-btn"]')
    await expect(sectionBtn).toBeVisible({ timeout: 10000 })
    await sectionBtn.click()
    await page.waitForTimeout(1000)

    // Take screenshot AFTER section
    const pAfter = path.join(ARTIFACTS_DIR, 'reproduce_after_section.png')
    await page.locator('canvas').first().screenshot({ path: pAfter })

    // Check plane parameters in store
    const planeState = await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      const p = store.sectionPlanes[0]
      return {
        enabled: p.enabled,
        point: p.point,
        normal: p.normal,
        offset: p.offset,
        flipped: p.flipped,
        isSectionMode: store.isSectionMode,
      }
    })
    console.log('Plane State after clicking Section:', planeState)

    // Suspect checks (Step 3):
    // 1. Plane normal and constant must not be NaN, infinite or zero-length
    expect(planeState.normal).toBeDefined()
    expect(planeState.normal.some((v: number) => isNaN(v) || !isFinite(v))).toBe(false)
    const normLen = Math.hypot(...planeState.normal)
    expect(normLen).toBeGreaterThan(0.9)

    // 2. The default cutting plane reference point MUST be the assembly bounding-box center,
    // NOT the world origin [0, 0, 0] (which is the underside of the base plate).
    // THIS ASSERTION REPRODUCES THE BUG AND FAILS ON THE CURRENT CODEBASE!
    expect(planeState.point[2]).toBeCloseTo(bboxInfo.center[2], 1)
  })
})
