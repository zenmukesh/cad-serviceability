import { test, expect } from '@playwright/test'
import * as path from 'path'

const ARTIFACTS_DIR = 'C:/Users/Mukesh/.gemini/antigravity/brain/e88bf82a-79b1-4096-a674-bc25b6ae4ad0'

test.describe('PART 2: Engineering-Graphics-Style Sectioning', () => {
  test.beforeEach(async ({ page }) => {
    test.setTimeout(60000)
    await page.goto('http://127.0.0.1:5173')
    await page.waitForFunction(() => {
      const store = (window as any).useAssemblyStore?.getState?.()
      return store && store.components && store.components.length > 0
    }, { timeout: 30000 })
    await page.waitForSelector('canvas', { timeout: 15000 })
    await page.waitForTimeout(500)
  })

  test('2.1 & 2.7: Plane maths, tilt badge text and reference plane normals', async ({ page }) => {
    const mathResults = await page.evaluate(async () => {
      const getStore = () => (window as any).useAssemblyStore.getState()

      // Top 0 deg
      getStore().setSectionPlaneFromSimple('Top')
      const pTop0 = getStore().sectionPlanes[0]

      // Top 30 deg toward Side (perpendicular to Front)
      getStore().setSectionTiltToward('Side')
      getStore().setSectionTiltDeg(30)
      const pTop30 = getStore().sectionPlanes[0]

      // Front 0 deg
      getStore().setSectionPlaneFromSimple('Front')
      const pFront0 = getStore().sectionPlanes[0]

      // Side 0 deg
      getStore().setSectionPlaneFromSimple('Side')
      const pSide0 = getStore().sectionPlanes[0]

      return {
        top0: { normal: pTop0.normal, label: pTop0.label },
        top30: { normal: pTop30.normal, label: pTop30.label },
        front0: { normal: pFront0.normal, label: pFront0.label },
        side0: { normal: pSide0.normal, label: pSide0.label },
      }
    })

    // Assert Top view section
    expect(mathResults.top0.label).toContain('Top view section')
    expect(mathResults.top0.normal[2]).toBeCloseTo(1.0, 2) // Z=1

    // Assert 30 deg inclined to Top, perpendicular to Front
    expect(mathResults.top30.label).toBe('Inclined 30 deg to Top, perpendicular to Front')
    expect(mathResults.top30.normal[0]).toBeCloseTo(Math.sin(30 * Math.PI / 180), 2) // X = sin(30)
    expect(mathResults.top30.normal[2]).toBeCloseTo(Math.cos(30 * Math.PI / 180), 2) // Z = cos(30)

    // Assert Front view section
    expect(mathResults.front0.label).toContain('Front view section')
    expect(mathResults.front0.normal[1]).toBeCloseTo(-1.0, 2) // Y = -1

    // Assert Side view section
    expect(mathResults.side0.label).toContain('Side view section')
    expect(mathResults.side0.normal[0]).toBeCloseTo(1.0, 2) // X = 1
  })

  test('2.2 & 2.5: Enabling section mounts compact bar & gizmo; closing leaves zero section artifacts', async ({ page }) => {
    // Click the Section button in toolbar
    const sectionBtn = page.locator('[data-testid="toolbar-section-btn"]')
    await sectionBtn.click()

    // Compact bar should now be visible at bottom center
    const bar = page.locator('[data-testid="compact-section-bar"]')
    await expect(bar).toBeVisible()

    // Gizmo badge should be visible
    const badge = page.locator('[data-testid="section-gizmo-badge"]')
    await expect(badge).toBeVisible()
    await expect(badge).toContainText('section')

    // Close section via Esc key
    await page.keyboard.press('Escape')
    await page.waitForTimeout(300)

    // Verify compact bar, gizmo badge, and outlines are completely removed
    await expect(bar).not.toBeVisible()
    await expect(badge).not.toBeVisible()

    const isSectionClean = await page.evaluate(() => {
      const s = (window as any).useAssemblyStore.getState()
      return {
        isSectionMode: s.isSectionMode,
        activeSectionResult: s.activeSectionResult,
        planesEnabled: s.sectionPlanes.some((p: any) => p.enabled),
      }
    })
    expect(isSectionClean.isSectionMode).toBe(false)
    expect(isSectionClean.activeSectionResult).toBeNull()
    expect(isSectionClean.planesEnabled).toBe(false)
  })

  test('2.3b & 2.7: True shape camera direction equals plane normal', async ({ page }) => {
    // Enable section mode with Front plane
    await page.evaluate(() => {
      const s = (window as any).useAssemblyStore.getState()
      s.setSectionPlaneFromSimple('Front')
    })
    await page.waitForTimeout(300)

    // Click True shape button
    const trueShapeBtn = page.locator('[data-testid="section-true-shape-btn"]')
    await trueShapeBtn.click()
    await page.waitForTimeout(600)

    // Check camera orientation and orthographic projection
    const camInfo = await page.evaluate(() => {
      const viewer = (window as any).__CAD_VIEWER__
      const store = (window as any).useAssemblyStore.getState()
      const pos = viewer.getCameraPosition()
      const tgt = viewer.getCameraTarget()
      const dir = [pos[0] - tgt[0], pos[1] - tgt[1], pos[2] - tgt[2]]
      const len = Math.hypot(...dir)
      const normDir = [dir[0] / len, dir[1] / len, dir[2] / len]

      return {
        isOrtho: viewer.isOrthographic(),
        projectionSetting: store.navSettings.projection,
        isTrueShapeActive: store.isTrueShapeActive,
        normDir,
        activePlane: store.sectionPlanes[0],
      }
    })

    expect(camInfo.isTrueShapeActive).toBe(true)
    expect(camInfo.projectionSetting).toBe('orthographic')

    // In CAD coordinates: Front normal is [0, -1, 0].
    // Three.js world mapping (nx, nz, -ny) -> [0, 0, 1] (+Z axis in Three.js).
    // The camera should be positioned along +Z looking at (0,0,0).
    expect(camInfo.normDir[2]).toBeCloseTo(1.0, 1)

    // Toggle True Shape off to return to previous camera
    await trueShapeBtn.click()
    await page.waitForTimeout(600)

    const restoredSetting = await page.evaluate(() => {
      return (window as any).useAssemblyStore.getState().navSettings.projection
    })
    expect(restoredSetting).toBe('perspective')
  })

  test('2.7: Flow - Enable section, choose Front, drag offset, tilt 30 deg, True shape (<= 5 interactions)', async ({ page }) => {
    // Count interactions:
    // Interaction 1: Click "Section" button
    const sectionBtn = page.locator('[data-testid="toolbar-section-btn"]')
    await sectionBtn.click()
    await expect(page.locator('[data-testid="compact-section-bar"]')).toBeVisible()

    // Interaction 2: Choose "Front" reference plane
    const frontBtn = page.locator('[data-testid="section-ref-front"]')
    await frontBtn.click()

    // Interaction 3: Drag offset slider
    const offsetSlider = page.locator('[data-testid="section-offset-slider"]')
    await offsetSlider.evaluate((el: HTMLInputElement) => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
      nativeSetter?.call(el, '25')
      el.dispatchEvent(new Event('input', { bubbles: true }))
    })

    // Interaction 4: Drag tilt slider to 30 deg
    const tiltSlider = page.locator('[data-testid="section-tilt-slider"]')
    await tiltSlider.evaluate((el: HTMLInputElement) => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
      nativeSetter?.call(el, '30')
      el.dispatchEvent(new Event('input', { bubbles: true }))
    })

    // Interaction 5: Click True shape
    const trueShapeBtn = page.locator('[data-testid="section-true-shape-btn"]')
    await trueShapeBtn.click()
    await page.waitForTimeout(500)

    // Verify all 5 actions took effect cleanly
    const state = await page.evaluate(() => {
      const s = (window as any).useAssemblyStore.getState()
      return {
        isSectionMode: s.isSectionMode,
        refPlane: s.sectionRefPlane,
        offset: s.sectionOffsetMm,
        tilt: s.sectionTiltDeg,
        isTrueShape: s.isTrueShapeActive,
      }
    })

    expect(state.isSectionMode).toBe(true)
    expect(state.refPlane).toBe('Front')
    expect(state.offset).toBe(25)
    expect(state.tilt).toBe(30)
    expect(state.isTrueShape).toBe(true)
  })

  test('Screenshots: Capture 30 deg inclined section with hatching & True shape view', async ({ page }) => {
    // 1. Setup 30 deg inclined section with hatching
    await page.evaluate(() => {
      const s = (window as any).useAssemblyStore.getState()
      s.setSectionPlaneFromSimple('Top')
      s.setSectionTiltToward('Side')
      s.setSectionTiltDeg(30)
      s.setSectionOffsetMm(15)
      if (!s.sectionHatchEnabled) s.toggleSectionHatch()
    })
    await page.waitForTimeout(1000)

    // Capture screenshot: 30 deg inclined section with hatching
    const p1 = path.join(ARTIFACTS_DIR, 'screenshot_inclined_section_hatching.png')
    await page.screenshot({ path: p1, fullPage: false })

    // 2. Activate True shape view
    const trueShapeBtn = page.locator('[data-testid="section-true-shape-btn"]')
    await trueShapeBtn.click()
    await page.waitForTimeout(1000)

    // Capture screenshot: True shape auxiliary view
    const p2 = path.join(ARTIFACTS_DIR, 'screenshot_true_shape_view.png')
    await page.screenshot({ path: p2, fullPage: false })

    expect(true).toBe(true)
  })
})
