import { test, expect } from '@playwright/test'
import * as path from 'path'
import * as fs from 'fs'

const ARTIFACTS_DIR = 'C:/Users/Mukesh/.gemini/antigravity/brain/e88bf82a-79b1-4096-a674-bc25b6ae4ad0'

// Simple pixel analyzer helper using pure JS in Node/Playwright
function countNonBackgroundPixels(buffer: Buffer): { total: number; nonBg: number; ratio: number } {
  // Simple heuristic: read raw PNG or parse using canvas/evaluate
  // Since Playwright runs in Node, we can also evaluate inside page.evaluate on an OffscreenCanvas or ImageBitmap
  return { total: 0, nonBg: 0, ratio: 0 }
}

test.describe('Step 5: Section Fix Verification & Deliverables', () => {
  test('Verify Top, Front, Side planes, 30 deg tilt with hatch, offset sweep, no NaNs, no 100% clip', async ({ page }) => {
    test.setTimeout(90000)

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
    await page.waitForTimeout(1500)

    // Helper inside browser to count non-bg pixels accurately from canvas
    const getCanvasPixelStats = async () => {
      return await page.evaluate(() => {
        const canvas = document.querySelector('canvas') as HTMLCanvasElement
        if (!canvas) return { total: 0, nonBg: 0, ratio: 0 }
        const w = canvas.width
        const h = canvas.height
        // Render to 2D canvas via webgl or copy
        const gl = canvas.getContext('webgl2') || canvas.getContext('webgl')
        if (!gl) return { total: 0, nonBg: 0, ratio: 0 }
        const pixels = new Uint8Array(w * h * 4)
        gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
        let nonBg = 0
        const total = w * h
        for (let i = 0; i < pixels.length; i += 4) {
          const r = pixels[i]
          const g = pixels[i + 1]
          const b = pixels[i + 2]
          const a = pixels[i + 3]
          // Background is #0a0f1d (10, 15, 29) or transparent/dark
          if (a > 0 && (Math.abs(r - 10) > 10 || Math.abs(g - 15) > 10 || Math.abs(b - 29) > 10)) {
            nonBg++
          }
        }
        return { total, nonBg, ratio: total > 0 ? nonBg / total : 0 }
      })
    }

    // 1. Baseline pixel count (without section)
    const baselineStats = await getCanvasPixelStats()
    console.log('[BASELINE STATS]:', baselineStats)
    const pBaseline = path.join(ARTIFACTS_DIR, 'verification_baseline.png')
    await page.locator('canvas').first().screenshot({ path: pBaseline })

    // 2. Enable Section Mode
    const sectionBtn = page.locator('[data-testid="toolbar-section-btn"]')
    await expect(sectionBtn).toBeVisible()
    await sectionBtn.click()
    await page.waitForTimeout(1000)

    // Verify section bar is visible
    const sectionBar = page.locator('[data-testid="compact-section-bar"]')
    await expect(sectionBar).toBeVisible()

    // 3. Test TOP Plane (Default view)
    const topStats = await getCanvasPixelStats()
    console.log('[TOP PLANE STATS]:', topStats)
    const pTop = path.join(ARTIFACTS_DIR, 'screenshot_section_top.png')
    await page.locator('canvas').first().screenshot({ path: pTop })

    // Top plane must show >= 30% of the baseline model pixels
    if (baselineStats.nonBg > 0) {
      const topModelRatio = topStats.nonBg / baselineStats.nonBg
      console.log(`Top plane model retention ratio: ${(topModelRatio * 100).toFixed(1)}%`)
      expect(topModelRatio).toBeGreaterThanOrEqual(0.3)
    }

    // 4. Test FRONT Plane
    const frontBtn = page.locator('[data-testid="section-ref-front"]')
    await frontBtn.click()
    await page.waitForTimeout(800)

    const frontStats = await getCanvasPixelStats()
    console.log('[FRONT PLANE STATS]:', frontStats)
    const pFront = path.join(ARTIFACTS_DIR, 'screenshot_section_front.png')
    await page.locator('canvas').first().screenshot({ path: pFront })

    if (baselineStats.nonBg > 0) {
      const frontModelRatio = frontStats.nonBg / baselineStats.nonBg
      console.log(`Front plane model retention ratio: ${(frontModelRatio * 100).toFixed(1)}%`)
      expect(frontModelRatio).toBeGreaterThanOrEqual(0.3)
    }

    // 5. Test SIDE Plane
    const sideBtn = page.locator('[data-testid="section-ref-side"]')
    await sideBtn.click()
    await page.waitForTimeout(800)

    const sideStats = await getCanvasPixelStats()
    console.log('[SIDE PLANE STATS]:', sideStats)

    if (baselineStats.nonBg > 0) {
      const sideModelRatio = sideStats.nonBg / baselineStats.nonBg
      console.log(`Side plane model retention ratio: ${(sideModelRatio * 100).toFixed(1)}%`)
      expect(sideModelRatio).toBeGreaterThanOrEqual(0.3)
    }

    // 6. Test TILT 30 DEG WITH HATCH
    // Switch back to Top plane and set tilt to 30 deg
    const topBtn = page.locator('[data-testid="section-ref-top"]')
    await topBtn.click()
    await page.waitForTimeout(400)

    await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      store.setSectionTiltDeg(30)
      if (!store.sectionHatchEnabled) {
        store.toggleSectionHatch()
      }
    })
    await page.waitForTimeout(800)

    const tilt30Stats = await getCanvasPixelStats()
    console.log('[TILT 30 DEG STATS]:', tilt30Stats)
    const pTilt30 = path.join(ARTIFACTS_DIR, 'screenshot_section_tilt30_hatch.png')
    await page.locator('canvas').first().screenshot({ path: pTilt30 })

    if (baselineStats.nonBg > 0) {
      const tiltModelRatio = tilt30Stats.nonBg / baselineStats.nonBg
      console.log(`Tilt 30 deg model retention ratio: ${(tiltModelRatio * 100).toFixed(1)}%`)
      expect(tiltModelRatio).toBeGreaterThanOrEqual(0.3)
    }

    // 7. Sweep offset from minimum to maximum
    const slider = page.locator('[data-testid="section-offset-slider"]')
    await expect(slider).toBeVisible()

    const minOffset = await slider.getAttribute('min').then((v) => parseFloat(v || '-60'))
    const maxOffset = await slider.getAttribute('max').then((v) => parseFloat(v || '60'))
    console.log(`Sweeping offset from ${minOffset} to ${maxOffset} mm...`)

    const steps = 9
    for (let i = 0; i <= steps; i++) {
      const testVal = minOffset + (maxOffset - minOffset) * (i / steps)
      await page.evaluate((val) => {
        const store = (window as any).useAssemblyStore.getState()
        store.setSectionOffsetMm(val)
      }, testVal)
      await page.waitForTimeout(50)

      const state = await page.evaluate(() => {
        const store = (window as any).useAssemblyStore.getState()
        const p = store.sectionPlanes[0]
        return {
          offset: store.sectionOffsetMm,
          planeOffset: p.offset,
          point: p.point,
          normal: p.normal,
        }
      })

      // Assert NO NaN produced
      expect(isNaN(state.offset)).toBe(false)
      expect(isNaN(state.planeOffset)).toBe(false)
      expect(state.point.some((n: number) => isNaN(n) || !isFinite(n))).toBe(false)
      expect(state.normal.some((n: number) => isNaN(n) || !isFinite(n))).toBe(false)
    }

    // Reset offset to 0
    await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      store.setSectionOffsetMm(0)
    })
    await page.waitForTimeout(300)

    // 8. Disable section mode: no section objects remain
    const closeBtn = page.locator('[data-testid="compact-section-bar"] button').filter({ hasText: '' }).last()
    await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      store.closeSectionMode()
    })
    await page.waitForTimeout(600)

    const finalState = await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      return {
        isSectionMode: store.isSectionMode,
        sectionPlanesEnabled: store.sectionPlanes.map((p: any) => p.enabled),
      }
    })
    expect(finalState.isSectionMode).toBe(false)
    expect(finalState.sectionPlanesEnabled[0]).toBe(false)

    // Check console errors
    const fatalErrors = consoleErrors.filter(
      (e) => !e.includes('favicon') && !e.includes('ResizeObserver') && !e.includes('React DevTools')
    )
    expect(fatalErrors).toHaveLength(0)
  })
})
