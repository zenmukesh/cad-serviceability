import { test, expect } from '@playwright/test'
import * as path from 'path'

const ARTIFACTS_DIR = 'C:/Users/Mukesh/.gemini/antigravity/brain/e88bf82a-79b1-4096-a674-bc25b6ae4ad0'

test.describe('Verify Fixes for User Visual Issues', () => {
  test.beforeEach(async ({ page }) => {
    test.setTimeout(60000)
    await page.goto('http://127.0.0.1:5173')
    await page.waitForFunction(() => {
      const store = (window as any).useAssemblyStore?.getState?.()
      const isExtracting = document.body.innerText.includes('Extracting CAD Meshes')
      return store && store.components && store.components.length === 19 && store.isLoading === false && !isExtracting
    }, { timeout: 45000 })
    await page.waitForSelector('canvas', { timeout: 15000 })
    await page.waitForTimeout(1000)
  })

  test('Issue 1: Selecting a component shows clean, compact removal arrow and clearly visible assembly', async ({ page }) => {
    // Select Motor in assembly store
    await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      const motor = store.components.find((c: any) => c.display_name.toLowerCase().includes('motor'))
      if (motor) store.selectComponent(motor.id)
    })

    // Check that access vector label is visible and formatted properly
    const accessLabel = page.locator('[data-testid="access-vector-label"]')
    await expect(accessLabel).toBeVisible({ timeout: 15000 })
    await expect(accessLabel).toContainText('-X')

    // Verify label bounding box is small and compact (not huge)
    const labelBox = await accessLabel.boundingBox()
    expect(labelBox).not.toBeNull()
    if (labelBox) {
      expect(labelBox.width).toBeLessThan(250)
      expect(labelBox.height).toBeLessThan(60)
    }

    await page.waitForTimeout(1000)

    // Capture screenshot
    const shotPath = path.join(ARTIFACTS_DIR, 'screenshot_component_selected_fix.png')
    await page.screenshot({ path: shotPath })
  })

  test('Issue 2: Section command shows compact live badge at bottom bar without obscuring model center', async ({ page }) => {
    // Click Section button
    const sectionBtn = page.locator('[data-testid="toolbar-section-btn"]')
    await sectionBtn.click()
    await page.waitForTimeout(1000)

    // Compact bar and badge should both be visible
    const bar = page.locator('[data-testid="compact-section-bar"]')
    await expect(bar).toBeVisible()

    const badge = page.locator('[data-testid="section-gizmo-badge"]')
    await expect(badge).toBeVisible()
    await expect(badge).toContainText('section')

    // Verify badge is positioned at bottom of viewport, not in the center
    const badgeBox = await badge.boundingBox()
    expect(badgeBox).not.toBeNull()
    if (badgeBox) {
      // Badge should be located in the bottom 30% of the window
      const viewportHeight = page.viewportSize()?.height || 720
      expect(badgeBox.y).toBeGreaterThan(viewportHeight * 0.6)
    }

    await page.waitForTimeout(500)

    // Capture screenshot
    const shotPath = path.join(ARTIFACTS_DIR, 'screenshot_section_mode_fix.png')
    await page.screenshot({ path: shotPath })

    // Close section mode via Escape
    await page.keyboard.press('Escape')
    await page.waitForTimeout(300)
    await expect(bar).not.toBeVisible()
    await expect(badge).not.toBeVisible()
  })
})
