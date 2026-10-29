import { test } from '@playwright/test'
import * as path from 'path'

const ARTIFACTS_DIR = 'C:/Users/Mukesh/.gemini/antigravity/brain/e88bf82a-79b1-4096-a674-bc25b6ae4ad0'

test('Reproduce shaft click in blind assembly', async ({ page }) => {
  test.setTimeout(90000)
  await page.setViewportSize({ width: 1400, height: 900 })
  await page.goto('http://127.0.0.1:5173')
  await page.waitForSelector('canvas', { timeout: 30000 })
  await page.waitForTimeout(2000)

  // Switch to blind_serviceability_test.step
  const blindOption = await page.locator('header select option').filter({ hasText: 'blind_serviceability_test' }).first().getAttribute('value')
  if (blindOption) {
    await page.selectOption('header select', blindOption)
  }
  console.log('Selected blind_serviceability_test option:', blindOption)

  // Wait until components are loaded
  await page.waitForFunction(() => {
    const store = (window as any).useAssemblyStore?.getState?.()
    return store && store.components && store.components.length === 20 && !store.isLoading
  }, { timeout: 45000 })

  console.log('20 components loaded')
  await page.waitForTimeout(2000)

  // Wait until analysis finishes
  console.log('Waiting for serviceability analysis to complete...')
  await page.waitForFunction(() => {
    const store = (window as any).useAssemblyStore?.getState?.()
    return store && store.serviceabilityReport != null && store.dependencyGraph != null
  }, { timeout: 90000 })
  console.log('Analysis completed!')

  // Click FRONT on ViewCube
  await page.evaluate(() => {
    ;(window as any).__VIEW_CUBE__?.clickFace('FRONT')
  })
  await page.waitForTimeout(1000)

  // Click Sequence tab in right panel
  const seqTab = page.locator('button:has-text("Sequence")')
  if (await seqTab.isVisible()) {
    await seqTab.click()
    await page.waitForTimeout(1000)
  }

  // Click Service_Shaft
  const shaftRow = page.locator('aside').getByText('Service_Shaft').first()
  await shaftRow.click()
  console.log('Clicked Service_Shaft')
  await page.waitForTimeout(3000)

  // Take screenshot after clicking Service Shaft
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'scratch_blind_shaft_clicked.png') })

  // Inspect the scene objects
  const sceneInfo = await page.evaluate(() => {
    const scene = (window as any).__THREE_SCENE__
    if (!scene) return { error: 'No __THREE_SCENE__' }

    const objects: any[] = []
    scene.traverse((obj: any) => {
      if (obj.isMesh || obj.isLine || obj.type === 'Mesh') {
        const bbox = obj.geometry ? {
          boundingSphere: obj.geometry.boundingSphere ? {
            radius: obj.geometry.boundingSphere.radius,
            center: [obj.geometry.boundingSphere.center.x, obj.geometry.boundingSphere.center.y, obj.geometry.boundingSphere.center.z]
          } : null
        } : null
        const isCyan = obj.material?.color && (obj.material.color.getHexString() === '38bdf8' || obj.material.color.getHexString() === '06b6d4' || obj.material.color.getHexString() === '00ffff')
        objects.push({
          name: obj.name || obj.type,
          type: obj.type,
          visible: obj.visible,
          isCyan,
          colorHex: obj.material?.color ? obj.material.color.getHexString() : null,
          position: [obj.position.x, obj.position.y, obj.position.z],
          scale: [obj.scale.x, obj.scale.y, obj.scale.z],
          bbox,
        })
      }
    })
    return { count: objects.length, objects }
  })

  console.log('Cyan objects:', JSON.stringify(sceneInfo.objects.filter((o: any) => o.isCyan), null, 2))
})
