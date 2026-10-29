import { test } from '@playwright/test'
import * as path from 'path'

const ARTIFACTS_DIR = 'C:/Users/Mukesh/.gemini/antigravity/brain/e88bf82a-79b1-4096-a674-bc25b6ae4ad0'

test('Simulate exact user state with report and sequence loaded', async ({ page }) => {
  test.setTimeout(90000)
  await page.setViewportSize({ width: 1024, height: 443 }) // EXACT user viewport!
  await page.goto('http://127.0.0.1:5173')
  await page.waitForSelector('canvas', { timeout: 30000 })
  await page.waitForTimeout(1000)

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

  // Directly inject the precomputed report and dependency graph into the store!
  await page.evaluate(async (assemblyId) => {
    const repRes = await fetch(`/api/assemblies/${assemblyId}/serviceability?min_clearance_mm=3`)
    const rep = await repRes.json()
    const depRes = await fetch(`/api/assemblies/${assemblyId}/dependency-graph`)
    const dep = await depRes.json()

    const store = (window as any).useAssemblyStore.getState()
    store.setServiceabilityReport(rep)
    store.setDependencyGraph(dep)
    store.setRightPanelTab('disassembly') // Sequence tab!
  }, blindOption)

  await page.waitForTimeout(1000)

  // Click FRONT on ViewCube
  await page.evaluate(() => {
    ;(window as any).__VIEW_CUBE__?.clickFace('FRONT')
  })
  await page.waitForTimeout(500)

  // Click Service_Shaft
  const shaftRow = page.locator('aside').getByText('Service_Shaft').first()
  await shaftRow.click()
  console.log('Clicked Service_Shaft')
  await page.waitForTimeout(2000)

  // Screenshot!
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'scratch_exact_user_reproduction.png') })

  // Find all cyan pixels on canvas
  const canvasStats = await page.evaluate(() => {
    const canvas = document.querySelector('canvas')
    if (!canvas) return null
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl')
    if (!gl) return null
    const pixels = new Uint8Array(canvas.width * canvas.height * 4)
    gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
    let cyan = 0
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i+2] > 200 && pixels[i+1] > 180 && pixels[i] < 100) cyan++
    }
    return { width: canvas.width, height: canvas.height, total: canvas.width * canvas.height, cyan }
  })
  console.log('Canvas cyan stats:', canvasStats)
})
