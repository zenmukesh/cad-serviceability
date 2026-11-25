import { test, expect } from '@playwright/test'

test.describe('Demo Smoke Test Suite', () => {
  test('Complete demo run-through: load gearbox, click component, visit all tabs with zero console errors and zero failed requests', async ({
    page,
  }) => {
    test.setTimeout(90000)

    const consoleErrors: string[] = []
    const failedRequests: string[] = []

    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text()
        // Ignore benign favicon 404 or known Three.js dev warnings if any
        if (!text.includes('favicon.ico')) {
          consoleErrors.push(text)
        }
      }
    })

    page.on('response', (response) => {
      const url = response.url()
      const status = response.status()
      if (status >= 400 && !url.includes('favicon.ico')) {
        failedRequests.push(`${response.request().method()} ${url} -> ${status}`)
      }
    })

    // 1. Navigate to application root
    await page.goto('/')
    await page.waitForSelector('canvas', { timeout: 30000 })

    // 2. Ensure gearbox is selected/loaded
    // Check if one-click demo button exists or select gearbox from dropdown
    const demoButton = page.locator('button:has-text("Load Demo Assembly")')
    if (await demoButton.isVisible()) {
      await demoButton.click()
    }

    // Wait for components to load in the assembly store
    await page.waitForFunction(
      () => {
        const store = (window as any).useAssemblyStore?.getState?.()
        return store && store.components && store.components.length >= 19 && !store.isLoading
      },
      { timeout: 45000 }
    )

    // 3. Select a component (e.g. Dipstick or Gear)
    await page.evaluate(() => {
      const store = (window as any).useAssemblyStore.getState()
      const target = store.components.find((c: any) =>
        c.display_name.toLowerCase().includes('dipstick') || c.display_name.toLowerCase().includes('gear')
      )
      if (target) {
        store.selectComponent(target.id)
      }
    })
    await page.waitForTimeout(500)

    // 4. Cycle through all right panel tabs
    const tabs: Array<{ id: string; label: string }> = [
      { id: 'score', label: 'Score' },
      { id: 'obstructions', label: 'Access' },
      { id: 'clearances', label: 'Clearance' },
      { id: 'disassembly', label: 'Sequence' },
      { id: 'revision', label: 'Compare' },
    ]

    for (const tab of tabs) {
      await page.evaluate((tabId) => {
        const store = (window as any).useAssemblyStore.getState()
        store.setRightPanelTab(tabId)
      }, tab.id)

      await page.waitForTimeout(800)

      // Ensure right panel container rendered for active tab
      const rightPanel = page.locator('aside').last()
      await expect(rightPanel).toBeVisible()
    }

    // 5. Verify zero errors and zero failed requests
    if (consoleErrors.length > 0) {
      console.error('Captured console errors:', consoleErrors)
    }
    if (failedRequests.length > 0) {
      console.error('Captured failed network requests:', failedRequests)
    }

    expect(consoleErrors).toEqual([])
    expect(failedRequests).toEqual([])
  })
})
