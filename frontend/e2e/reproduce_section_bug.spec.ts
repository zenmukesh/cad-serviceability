import { test, expect } from '@playwright/test'
import * as path from 'path'
import * as fs from 'fs'

const ARTIFACTS_DIR = 'C:/Users/Mukesh/.gemini/antigravity/brain/e88bf82a-79b1-4096-a674-bc25b6ae4ad0'

test.describe('Step 1: Reproduce Section Blank Canvas Bug', () => {
  test('Reproduce: clicking Section blanks the 3D canvas', async ({ page }) => {
    test.setTimeout(60000)

    const consoleLogs: string[] = []
    const consoleErrors: string[] = []

    page.on('console', (msg) => {
      const text = msg.text()
      consoleLogs.push(`[${msg.type()}] ${text}`)
      if (msg.type() === 'error') consoleErrors.push(text)
    })

    page.on('pageerror', (err) => {
      consoleErrors.push(`[PAGE ERROR] ${err.message}\n${err.stack}`)
    })

    await page.goto('http://127.0.0.1:5173')
    await page.waitForSelector('canvas', { timeout: 30000 })

    // Wait for assembly to load
    await page.waitForFunction(() => {
      const store = (window as any).useAssemblyStore?.getState?.()
      return store && store.components && store.components.length > 0
    }, { timeout: 30000 })
    await page.waitForTimeout(1500)

    // Hook webglcontextlost and WebGL error checking
    await page.evaluate(() => {
      const canvas = document.querySelector('canvas') as HTMLCanvasElement
      if (canvas) {
        canvas.addEventListener('webglcontextlost', (e) => {
          console.error('[WEBGL CONTEXT LOST]', e)
        })
      }
    })

    // Take screenshot BEFORE Section
    const pBefore = path.join(ARTIFACTS_DIR, 'reproduce_before_section.png')
    const beforeBuffer = await page.locator('canvas').first().screenshot({ path: pBefore })

    // Count non-background pixels from the canvas screenshot
    // Canvas background is #0a0f1d: R=10, G=15, B=29
    const countModelPixels = async () => {
      return await page.evaluate(() => {
        const canvas = document.querySelector('canvas') as HTMLCanvasElement
        if (!canvas) return { error: 'No canvas' }
        const gl = canvas.getContext('webgl2') || canvas.getContext('webgl')
        if (!gl) return { error: 'No GL' }

        const err = gl.getError()
        const glErrorStr = err === 0 ? 'NO_ERROR' : `GL_ERROR_${err}`

        // Also check if any shader compilation failed
        return {
          glError: glErrorStr,
          drawingWidth: gl.drawingBufferWidth,
          drawingHeight: gl.drawingBufferHeight,
        }
      })
    }

    const glInfoBefore = await countModelPixels()
    console.log('GL Info Before Section:', glInfoBefore)

    // Click Section button in toolbar
    const sectionBtn = page.locator('[data-testid="toolbar-section-btn"]')
    await expect(sectionBtn).toBeVisible({ timeout: 10000 })
    await sectionBtn.click()

    await page.waitForTimeout(1000)

    // Take screenshot AFTER Section
    const pAfter = path.join(ARTIFACTS_DIR, 'reproduce_after_section.png')
    const afterBuffer = await page.locator('canvas').first().screenshot({ path: pAfter })

    // Check WebGL diagnostics after section
    const glInfoAfter = await page.evaluate(() => {
      const canvas = document.querySelector('canvas') as HTMLCanvasElement
      if (!canvas) return { error: 'No canvas' }
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl')
      if (!gl) return { error: 'No GL' }

      const err = gl.getError()
      const glErrorStr = err === 0 ? 'NO_ERROR' : `GL_ERROR_${err}`

      // Check Three.js scene state
      const store = (window as any).useAssemblyStore.getState()
      const plane = store.sectionPlanes[0]

      return {
        glError: glErrorStr,
        isSectionMode: store.isSectionMode,
        sectionRefPlane: store.sectionRefPlane,
        plane: {
          enabled: plane?.enabled,
          normal: plane?.normal,
          offset: plane?.offset,
          point: plane?.point,
          flipped: plane?.flipped,
        },
      }
    })

    console.log('GL Info After Section:', JSON.stringify(glInfoAfter, null, 2))
    console.log('Console Errors:', consoleErrors)

    // Compare screenshot file sizes or pixel buffers:
    // If canvas is blank (solid background #0a0f1d), the PNG file size will be drastically smaller,
    // or we can analyze the PNG buffer / pixel colors!
    console.log(`Before screenshot size: ${beforeBuffer.length} bytes`)
    console.log(`After screenshot size: ${afterBuffer.length} bytes`)

    // Evaluate pixel difference directly in browser by rendering the canvas to a 2d context or reading pixels
    const pixelAnalysis = await page.evaluate(() => {
      // Create a 2D canvas to read back the WebGL canvas pixels
      const webglCanvas = document.querySelector('canvas') as HTMLCanvasElement
      if (!webglCanvas) return { nonBgPixels: 0, totalPixels: 0 }

      const offscreen = document.createElement('canvas')
      offscreen.width = webglCanvas.width
      offscreen.height = webglCanvas.height
      const ctx = offscreen.getContext('2d')
      if (!ctx) return { nonBgPixels: 0, totalPixels: 0 }

      ctx.drawImage(webglCanvas, 0, 0)
      const imgData = ctx.getImageData(0, 0, offscreen.width, offscreen.height)
      const data = imgData.data

      let nonBg = 0
      const total = offscreen.width * offscreen.height

      // Background color #0a0f1d -> r=10, g=15, b=29
      for (let i = 0; i < data.length; i += 4) {
        const r = data[i]
        const g = data[i + 1]
        const b = data[i + 2]
        // Color difference threshold
        if (Math.abs(r - 10) > 15 || Math.abs(g - 15) > 15 || Math.abs(b - 29) > 15) {
          nonBg++
        }
      }

      return {
        nonBgPixels: nonBg,
        totalPixels: total,
        ratio: nonBg / total,
      }
    })

    console.log('Pixel Analysis After Section:', pixelAnalysis)

    // The test MUST FAIL before the fix:
    // When the bug is present, nonBgPixels is near 0 (< 1% or 0%), meaning the canvas is blank!
    // The requirement states: "The test must FAIL before the fix."
    // "For the Top, Front and Side planes and for tilt 30 deg, the default view must show at least 30 percent of the model's pixels."
    expect(pixelAnalysis.nonBgPixels).toBeGreaterThan(1000)
    expect(pixelAnalysis.ratio).toBeGreaterThan(0.05)
  })
})
