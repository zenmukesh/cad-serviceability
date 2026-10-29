import { test, expect } from '@playwright/test'
import path from 'path'

const ARTIFACTS_DIR = 'C:/Users/Mukesh/.gemini/antigravity/brain/e88bf82a-79b1-4096-a674-bc25b6ae4ad0'

test('Capture Part 1 Navigation & ViewCube Screenshots', async ({ page }) => {
  await page.goto('/')
  await page.waitForFunction(() => (window as any).__CAD_VIEWER__ != null, { timeout: 10000 })

  // Wait for assembly to load if present
  await page.waitForTimeout(1500)

  // 1. Home / Isometric View
  await page.evaluate(() => (window as any).__VIEW_CUBE__.clickHome())
  await page.waitForTimeout(500)
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'screenshot_viewcube_home.png') })

  // 2. ViewCube TOP View
  await page.evaluate(() => (window as any).__VIEW_CUBE__.clickFace('TOP'))
  await page.waitForTimeout(500)
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'screenshot_viewcube_top.png') })

  // 3. ViewCube FRONT View
  await page.evaluate(() => (window as any).__VIEW_CUBE__.clickFace('FRONT'))
  await page.waitForTimeout(500)
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'screenshot_viewcube_front.png') })

  // 4. Free Tumble Angle 1 (arbitrary diagonal orbit)
  const canvas = page.locator('canvas').first()
  const box = await canvas.boundingBox()
  const cx = box!.x + box!.width / 2
  const cy = box!.y + box!.height / 2

  await page.keyboard.down('Shift')
  await page.mouse.move(cx, cy)
  await page.mouse.down({ button: 'middle' })
  await page.mouse.move(cx + 80, cy - 60, { steps: 5 })
  await page.mouse.up({ button: 'middle' })
  await page.keyboard.up('Shift')
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'screenshot_free_tumble_1.png') })

  // 5. Free Tumble Angle 2 (steep oblique tilt)
  await page.keyboard.down('Shift')
  await page.mouse.move(cx, cy)
  await page.mouse.down({ button: 'middle' })
  await page.mouse.move(cx - 120, cy + 90, { steps: 5 })
  await page.mouse.up({ button: 'middle' })
  await page.keyboard.up('Shift')
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'screenshot_free_tumble_2.png') })

  // 6. Free Tumble Angle 3 (underside diagonal perspective)
  await page.keyboard.down('Shift')
  await page.mouse.move(cx, cy)
  await page.mouse.down({ button: 'middle' })
  await page.mouse.move(cx + 140, cy + 110, { steps: 5 })
  await page.mouse.up({ button: 'middle' })
  await page.keyboard.up('Shift')
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'screenshot_free_tumble_3.png') })
})
