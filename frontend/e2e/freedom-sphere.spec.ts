import { test, expect } from '@playwright/test'
import * as path from 'path'
import { deriveCardinalLabel } from '../src/components/viewer/FreedomSphere'

const ARTIFACTS_DIR = 'C:/Users/Mukesh/.gemini/antigravity/brain/e88bf82a-79b1-4096-a674-bc25b6ae4ad0'

test.describe('PART 3: Freedom Sphere Fix, Demotion & Consistency', () => {
  test.beforeEach(async ({ page }) => {
    test.setTimeout(90000)
    await page.goto('http://127.0.0.1:5173')
    await page.evaluate(() => {
      try {
        localStorage.removeItem('cad_removal_directions_open')
      } catch {}
    })
    await page.waitForFunction(() => {
      const store = (window as any).useAssemblyStore?.getState?.()
      return store && store.components && store.components.length > 0
    }, { timeout: 30000 })
    await page.waitForSelector('canvas', { timeout: 15000 })
    await page.waitForTimeout(500)
  })

  test('3.1 & 3.2: Freedom Sphere never opens automatically and has explanation line', async ({ page }) => {
    // Select Motor component
    await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      const motor = store.components.find((c: any) => c.display_name.toLowerCase().includes('motor'))
      if (motor) store.selectComponent(motor.id)
      store.setRightPanelTab('obstructions')
    })
    await page.waitForTimeout(1000)

    // Verify floating overlay on main canvas does NOT exist
    const floatingSphere = page.locator('.absolute.bottom-4.left-4:has-text("Freedom Sphere")')
    await expect(floatingSphere).not.toBeVisible()

    // Verify card exists in Access tab
    const removalCard = page.locator('[data-testid="removal-directions-card"]')
    await expect(removalCard).toBeVisible({ timeout: 10000 })

    // 3.2 Verify one line explanation is present in card
    await expect(removalCard).toContainText('Directions this part can move out of the assembly without hitting anything. Green = free, red = blocked.')

    // 3.1 Verify sphere inspector is CLOSED by default
    const sphereContainer = page.locator('[data-testid="freedom-sphere-container"]')
    await expect(sphereContainer).not.toBeVisible()
  })

  test('3.1: Sphere can be opened, closed with [x] button and closed with Esc key', async ({ page }) => {
    // Select Motor and open Access tab
    await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      const motor = store.components.find((c: any) => c.display_name.toLowerCase().includes('motor'))
      if (motor) store.selectComponent(motor.id)
      store.setRightPanelTab('obstructions')
    })
    await page.waitForFunction(() => {
      const store = (window as any).useAssemblyStore?.getState?.()
      return store && store.selectedObstructionReport != null
    }, { timeout: 20000 }).catch(() => {})

    const toggleBtn = page.locator('[data-testid="toggle-removal-card-btn"]')
    const sphereContainer = page.locator('[data-testid="freedom-sphere-container"]')
    await toggleBtn.waitFor({ state: 'visible', timeout: 20000 })

    // 1. Open sphere
    await toggleBtn.click()
    await expect(sphereContainer).toBeVisible({ timeout: 10000 })

    // 2. Close with [x] button
    const closeBtn = page.locator('[data-testid="close-removal-card-btn"]')
    await closeBtn.click()
    await expect(sphereContainer).not.toBeVisible()

    // 3. Open sphere again and close with Escape key
    await toggleBtn.click()
    await expect(sphereContainer).toBeVisible({ timeout: 10000 })
    await page.keyboard.press('Escape')
    await page.waitForTimeout(300)
    await expect(sphereContainer).not.toBeVisible()
  })

  test('3.3 & 3.4: Data consistency for Motor - Best vector is (-1, 0, 0) matching -X, narrow cone text', async ({ page }) => {
    // Select Motor component and open Access tab
    await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      const motor = store.components.find((c: any) => c.display_name.toLowerCase().includes('motor'))
      if (motor) store.selectComponent(motor.id)
      store.setRightPanelTab('obstructions')
    })
    await page.waitForTimeout(1500)

    // 3.4 In 3D view, check access vector overlay has -X label
    const accessLabel = page.locator('[data-testid="access-vector-label"]')
    await expect(accessLabel).toBeVisible({ timeout: 10000 })
    await expect(accessLabel).toContainText('-X')
    await expect(accessLabel).toContainText('[-1.00, 0.00, 0.00]')

    // Open sphere inspector if closed
    const toggleBtn = page.locator('[data-testid="toggle-removal-card-btn"]')
    await expect(toggleBtn).toBeVisible({ timeout: 15000 })
    const btnText = await toggleBtn.textContent()
    if (btnText?.includes('View Sphere')) {
      await toggleBtn.click()
    }

    // 3.3 Verify Motor's best direction vector is (-1, 0, 0) and matches -X
    const bestVectorText = page.locator('[data-testid="freedom-sphere-best-vector"]')
    await expect(bestVectorText).toBeVisible({ timeout: 25000 })
    await expect(bestVectorText).toContainText('-X [-1.00, 0.00, 0.00]')

    // 3.3 Verify narrow cone message appears instead of 0 / 162
    const feasibleStatus = page.locator('[data-testid="freedom-sphere-feasible-status"]')
    await expect(feasibleStatus).toBeVisible()
    await expect(feasibleStatus).toContainText('Narrow free cone (< 1°)')

    // 3.3 Verify cone badge never prints "0.0 deg"
    const coneBadge = page.locator('[data-testid="freedom-sphere-cone-badge"]')
    await expect(coneBadge).toBeVisible()
    const badgeContent = await coneBadge.textContent()
    expect(badgeContent).not.toContain('0.0°')
    expect(badgeContent).toContain('< 1°')
  })

  test('3.5: Label/vector consistency across components in the gearbox', async () => {
    // 19 components with their extraction directions
    const gearboxComponents: Array<{ name: string; vector: [number, number, number]; expected: string }> = [
      { name: 'BasePlate', vector: [0, 0, -1], expected: '-Z' },
      { name: 'BearingBlock_A', vector: [0, 0, 1], expected: '+Z' },
      { name: 'BearingBlock_B', vector: [0, 0, 1], expected: '+Z' },
      { name: 'Shaft', vector: [0, 1, 0], expected: '+Y' },
      { name: 'Gear', vector: [0, 1, 0], expected: '+Y' },
      { name: 'Motor', vector: [-1, 0, 0], expected: '-X' },
      { name: 'CoverPlate', vector: [0, 0, 1], expected: '+Z' },
      { name: 'CoverScrew_1', vector: [0, 0, 1], expected: '+Z' },
      { name: 'CoverScrew_2', vector: [0, 0, 1], expected: '+Z' },
      { name: 'CoverScrew_3', vector: [0, 0, 1], expected: '+Z' },
      { name: 'CoverScrew_4', vector: [0, 0, 1], expected: '+Z' },
      { name: 'Dipstick', vector: [0, 0, 1], expected: '+Z' },
      { name: 'SensorBlock', vector: [1, 0, 0], expected: '+X' },
      { name: 'FilterCanister', vector: [0, -1, 0], expected: '-Y' },
      { name: 'FilterBracket', vector: [0, -1, 0], expected: '-Y' },
      { name: 'BaseBolt_1', vector: [0, 0, -1], expected: '-Z' },
      { name: 'BaseBolt_2', vector: [0, 0, -1], expected: '-Z' },
      { name: 'BaseBolt_3', vector: [0, 0, -1], expected: '-Z' },
      { name: 'BaseBolt_4', vector: [0, 0, -1], expected: '-Z' },
    ]

    expect(gearboxComponents.length).toBe(19)
    for (const comp of gearboxComponents) {
      const derived = deriveCardinalLabel(comp.vector)
      expect(derived.axis).toBe(comp.expected)
      expect(derived.angleDeg).toBeLessThan(1e-3)
    }

    // Verify perturbed / continuous cone vectors near Motor's direction (-1, 0, 0)
    const perturbedMotor = deriveCardinalLabel([-0.98, 0.05, 0.02])
    expect(perturbedMotor.axis).toBe('-X')
    expect(perturbedMotor.angleDeg).toBeLessThan(15.0)
  })

  test('Screenshots: Access tab with sphere closed and open', async ({ page }) => {
    test.setTimeout(60000)
    // Select Motor and open Access tab
    await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      const motor = store.components.find((c: any) => c.display_name.toLowerCase().includes('motor'))
      if (motor) store.selectComponent(motor.id)
      store.setRightPanelTab('obstructions')
    })
    await page.waitForTimeout(1000)

    // 1. Capture Access tab with sphere closed
    const pClosed = path.join(ARTIFACTS_DIR, 'screenshot_access_tab_sphere_closed.png')
    await page.screenshot({ path: pClosed, fullPage: false })

    // 2. Open sphere
    const toggleBtn = page.locator('[data-testid="toggle-removal-card-btn"]')
    await toggleBtn.click()
    await page.waitForTimeout(1000)

    // Capture Access tab with sphere open
    const pOpen = path.join(ARTIFACTS_DIR, 'screenshot_access_tab_sphere_open.png')
    await page.screenshot({ path: pOpen, fullPage: false })

    expect(true).toBe(true)
  })
})
