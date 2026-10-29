import { test, expect } from '@playwright/test'
import * as path from 'path'

const ARTIFACTS_DIR = 'C:/Users/Mukesh/.gemini/antigravity/brain/e88bf82a-79b1-4096-a674-bc25b6ae4ad0'

test.describe('Section Blank Canvas Bug', () => {
  test.beforeEach(async ({ page }) => {
    test.setTimeout(90000)
    await page.goto('http://127.0.0.1:5173')
    await page.waitForSelector('canvas', { timeout: 30000 })
    await page.waitForFunction(() => {
      const store = (window as any).useAssemblyStore?.getState?.()
      return store && store.components && store.components.length > 0
    }, { timeout: 30000 }).catch(() => {})
    await page.waitForTimeout(1000)
  })

  test('REPRODUCE: Enabling Section blanks the 3D canvas', async ({ page }) => {
    // Collect console errors
    const consoleErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })

    // 1. Screenshot BEFORE section (baseline)
    const pBefore = path.join(ARTIFACTS_DIR, 'screenshot_section_bug_BEFORE.png')
    await page.screenshot({ path: pBefore, fullPage: false })

    // 2. Count non-background pixels BEFORE section
    const pixelsBefore = await page.evaluate(() => {
      const canvas = document.querySelector('canvas') as HTMLCanvasElement
      if (!canvas) return -1
      const ctx = (canvas as any).__ctx2d
      // Use WebGL readPixels
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl')
      if (!gl) return -2
      const w = gl.drawingBufferWidth
      const h = gl.drawingBufferHeight
      const pixels = new Uint8Array(w * h * 4)
      gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
      let nonBg = 0
      // Background is ~#0a0f1d → R=10,G=15,B=29
      for (let i = 0; i < pixels.length; i += 4) {
        const r = pixels[i], g = pixels[i+1], b = pixels[i+2]
        // If pixel differs significantly from background
        if (Math.abs(r - 10) > 25 || Math.abs(g - 15) > 25 || Math.abs(b - 29) > 25) {
          nonBg++
        }
      }
      return nonBg
    })

    console.log('Pixels before section (non-background):', pixelsBefore)
    expect(pixelsBefore).toBeGreaterThan(1000) // model should be visible

    // 3. Enable section mode (Top plane, offset 0, tilt 0)
    await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      store.setIsSectionMode(true)
    })
    await page.waitForTimeout(500)

    // 4. Screenshot AFTER section
    const pAfter = path.join(ARTIFACTS_DIR, 'screenshot_section_bug_AFTER.png')
    await page.screenshot({ path: pAfter, fullPage: false })

    // 5. Check WebGL errors
    const webglErrors = await page.evaluate(() => {
      const canvas = document.querySelector('canvas') as HTMLCanvasElement
      if (!canvas) return 'no canvas'
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl')
      if (!gl) return 'no gl'
      const err = gl.getError()
      return err === 0 ? 'GL_NO_ERROR' : `GL_ERROR_${err}`
    })
    console.log('WebGL error:', webglErrors)

    // 6. Count non-background pixels AFTER section
    const pixelsAfter = await page.evaluate(() => {
      const canvas = document.querySelector('canvas') as HTMLCanvasElement
      if (!canvas) return -1
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl')
      if (!gl) return -2
      const w = gl.drawingBufferWidth
      const h = gl.drawingBufferHeight
      const pixels = new Uint8Array(w * h * 4)
      gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
      let nonBg = 0
      for (let i = 0; i < pixels.length; i += 4) {
        const r = pixels[i], g = pixels[i+1], b = pixels[i+2]
        if (Math.abs(r - 10) > 25 || Math.abs(g - 15) > 25 || Math.abs(b - 29) > 25) {
          nonBg++
        }
      }
      return nonBg
    })
    console.log('Pixels after section (non-background):', pixelsAfter)
    console.log('Console errors:', consoleErrors)

    // 7. Log suspects: plane normal, constant, offset
    const suspects = await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      const plane = store.sectionPlanes[0]
      return {
        planeEnabled: plane.enabled,
        planeNormal: plane.normal,
        planePoint: plane.point,
        planeOffset: plane.offset,
        planeFlipped: plane.flipped,
        sectionPlaneAxis: store.sectionPlaneAxis,
        sectionOffsetMm: store.sectionOffsetMm,
        isSectionMode: store.isSectionMode,
        normalLength: Math.sqrt(plane.normal[0]**2 + plane.normal[1]**2 + plane.normal[2]**2),
        normalHasNaN: plane.normal.some((v: number) => isNaN(v)),
        normalHasInf: plane.normal.some((v: number) => !isFinite(v)),
      }
    })
    console.log('Section suspects:', JSON.stringify(suspects, null, 2))

    // THIS TEST MUST FAIL before the fix: after enabling section, 
    // the model should still have > 30% of pre-section visible pixels
    const threshold = pixelsBefore * 0.3
    expect(pixelsAfter).toBeGreaterThan(threshold)
  })
})
