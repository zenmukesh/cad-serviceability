import { test, expect } from '@playwright/test'

test.describe('Part 1: Fusion-360-Style Navigation & ViewCube', () => {
  test.beforeEach(async ({ page }) => {
    test.setTimeout(90000)
    await page.goto('/')
    // Wait for components to load and viewer to be ready
    await page.waitForFunction(() => {
      const store = (window as any).useAssemblyStore?.getState?.()
      return store && store.components && store.components.length > 0 && !store.isLoading
    }, { timeout: 60000 })
    await page.waitForFunction(() => (window as any).__CAD_VIEWER__ != null, { timeout: 60000 })
    await page.waitForTimeout(500)
  })

  test('1.1 & 1.2: Diagonal Shift+middle drag rotates camera about two axes (free tumble)', async ({
    page,
  }) => {
    const qBefore: number[] = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getCameraQuaternion()
    )
    const posBefore: number[] = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getCameraPosition()
    )

    // Canvas center
    const canvas = page.locator('canvas').first()
    const box = await canvas.boundingBox()
    expect(box).not.toBeNull()

    const cx = box!.x + box!.width / 2
    const cy = box!.y + box!.height / 2

    // Perform diagonal Shift + Middle drag (Fusion 360 free orbit)
    await page.keyboard.down('Shift')
    await page.mouse.move(cx, cy)
    await page.mouse.down({ button: 'middle' })
    await page.mouse.move(cx + 100, cy - 80, { steps: 10 })
    await page.mouse.up({ button: 'middle' })
    await page.keyboard.up('Shift')

    await page.waitForTimeout(100)

    const qAfter: number[] = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getCameraQuaternion()
    )
    const posAfter: number[] = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getCameraPosition()
    )

    // Position must change in multiple coordinates
    const dx = Math.abs(posAfter[0] - posBefore[0])
    const dy = Math.abs(posAfter[1] - posBefore[1])
    const dz = Math.abs(posAfter[2] - posBefore[2])

    expect(dx + dy + dz).toBeGreaterThan(5.0)

    // Quaternion orientation must change across both axes (pitch and yaw/roll)
    const qDiffX = Math.abs(qAfter[0] - qBefore[0])
    const qDiffY = Math.abs(qAfter[1] - qBefore[1])
    expect(qDiffX + qDiffY).toBeGreaterThan(0.01)
  })

  test('1.2: Middle-mouse drag pans target without rotating camera', async ({ page }) => {
    const qBefore: number[] = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getCameraQuaternion()
    )
    const targetBefore: number[] = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getCameraTarget()
    )

    const canvas = page.locator('canvas').first()
    const box = await canvas.boundingBox()
    const cx = box!.x + box!.width / 2
    const cy = box!.y + box!.height / 2

    // Middle mouse drag without Shift = Pan
    await page.mouse.move(cx, cy)
    await page.mouse.down({ button: 'middle' })
    await page.mouse.move(cx + 120, cy + 90, { steps: 10 })
    await page.mouse.up({ button: 'middle' })

    await page.waitForTimeout(100)

    const qAfter: number[] = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getCameraQuaternion()
    )
    const targetAfter: number[] = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getCameraTarget()
    )

    // Target position must have moved
    const targetDist = Math.hypot(
      targetAfter[0] - targetBefore[0],
      targetAfter[1] - targetBefore[1],
      targetAfter[2] - targetBefore[2]
    )
    expect(targetDist).toBeGreaterThan(5.0)

    // Orientation must remain identical during pan (quaternion dot product ~ 1.0)
    const dot =
      qBefore[0] * qAfter[0] +
      qBefore[1] * qAfter[1] +
      qBefore[2] * qAfter[2] +
      qBefore[3] * qAfter[3]
    expect(Math.abs(dot)).toBeGreaterThan(0.999)
  })

  test('1.2: Wheel zoom changes camera distance to target', async ({ page }) => {
    const distBefore: number = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getTargetDistance()
    )

    const canvas = page.locator('canvas').first()
    const box = await canvas.boundingBox()
    const cx = box!.x + box!.width / 2
    const cy = box!.y + box!.height / 2

    await page.mouse.move(cx, cy)
    await page.mouse.wheel(0, -300) // Zoom in

    await page.waitForTimeout(200)

    const distAfter: number = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getTargetDistance()
    )
    expect(distAfter).toBeLessThan(distBefore)
  })

  test('1.3: Click vs drag threshold (>4px is drag, <4px is click)', async ({ page }) => {
    const canvas = page.locator('canvas').first()
    const box = await canvas.boundingBox()
    const cx = box!.x + box!.width / 2
    const cy = box!.y + box!.height / 2

    // Move only 2px: should be treated as click, target distance unchanged
    const posBefore: number[] = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getCameraPosition()
    )

    await page.mouse.move(cx, cy)
    await page.mouse.down({ button: 'left' })
    await page.mouse.move(cx + 2, cy + 1)
    await page.mouse.up({ button: 'left' })

    await page.waitForTimeout(100)

    const posAfter: number[] = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.getCameraPosition()
    )
    expect(Math.abs(posAfter[0] - posBefore[0])).toBeLessThan(0.01)
  })

  test('1.4: ViewCube face clicks orient camera along expected axes', async ({ page }) => {
    // Wait for ViewCube component to initialize
    await page.waitForFunction(() => (window as any).__VIEW_CUBE__ != null, { timeout: 15000 })

    // Test TOP, FRONT, and RIGHT views
    const testFaces = ['TOP', 'FRONT', 'RIGHT', 'BOTTOM', 'BACK', 'LEFT']

    for (const face of testFaces) {
      await page.evaluate((f) => (window as any).__VIEW_CUBE__.clickFace(f), face)
      // Wait for slerp transition (~350ms) to settle
      await page.waitForTimeout(600)

      const pos: number[] = await page.evaluate(() =>
        (window as any).__CAD_VIEWER__.getCameraPosition()
      )
      const target: number[] = await page.evaluate(() =>
        (window as any).__CAD_VIEWER__.getCameraTarget()
      )

      // Direction vector from target to camera
      const dir = [pos[0] - target[0], pos[1] - target[1], pos[2] - target[2]]
      const mag = Math.hypot(dir[0], dir[1], dir[2])
      const normDir = [dir[0] / mag, dir[1] / mag, dir[2] / mag]

      if (face === 'TOP') {
        // Looking down along -Y (CAD +Z)
        expect(normDir[1]).toBeGreaterThan(0.95)
      } else if (face === 'BOTTOM') {
        // Looking up along +Y (CAD -Z)
        expect(normDir[1]).toBeLessThan(-0.95)
      } else if (face === 'FRONT') {
        // Looking in along +Z
        expect(normDir[2]).toBeGreaterThan(0.95)
      } else if (face === 'BACK') {
        // Looking in along -Z
        expect(normDir[2]).toBeLessThan(-0.95)
      } else if (face === 'RIGHT') {
        // Looking in along +X
        expect(normDir[0]).toBeGreaterThan(0.95)
      } else if (face === 'LEFT') {
        // Looking in along -X
        expect(normDir[0]).toBeLessThan(-0.95)
      }
    }
  })

  test('1.4 & 1.6: Orthographic toggle switches projection', async ({ page }) => {
    const isOrthoInitial: boolean = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.isOrthographic()
    )
    expect(isOrthoInitial).toBe(false)

    // Open ViewCube context menu
    await page.getByTestId('view-cube-menu-btn').click()
    await page.getByText('Orthographic').click()

    await page.waitForTimeout(100)

    const isOrthoAfter: boolean = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.isOrthographic()
    )
    expect(isOrthoAfter).toBe(true)

    // Switch back to perspective
    await page.getByTestId('view-cube-menu-btn').click()
    await page.getByText('Perspective').click()

    await page.waitForTimeout(100)
    const isOrthoFinal: boolean = await page.evaluate(() =>
      (window as any).__CAD_VIEWER__.isOrthographic()
    )
    expect(isOrthoFinal).toBe(false)
  })
})
