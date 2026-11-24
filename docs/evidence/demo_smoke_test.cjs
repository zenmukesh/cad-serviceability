/**
 * Scripted Browser Demo Smoke Test & Performance Measurement
 * Fulfills Section 6 (Performance) and Section 7 (Demo Smoke Test).
 */
const { chromium } = require('d:/projects/cad-serviceability/frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');

const EVIDENCE_DIR = path.resolve(__dirname);
const BASE_URL = 'http://localhost:5173';

async function run() {
  console.log('=== STARTING DEMO SMOKE TEST ===');
  const browser = await chromium.launch({
    headless: true,
    args: ['--use-gl=angle', '--use-angle=default', '--enable-webgl'],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  const consoleErrors = [];
  const consoleLogs = [];
  const failedRequests = [];
  const networkRequests = [];

  page.on('console', (msg) => {
    const text = msg.text();
    consoleLogs.push({ type: msg.type(), text });
    if (msg.type() === 'error') {
      consoleErrors.push(text);
      console.error('[Browser Console Error]', text);
    }
  });

  page.on('response', (res) => {
    if (res.status() >= 400) {
      console.warn(`[HTTP Error ${res.status()}] ${res.request().method()} ${res.url()}`);
      failedRequests.push({
        url: res.url(),
        status: res.status(),
        statusText: res.statusText(),
        method: res.request().method(),
      });
    }
  });

  page.on('requestfailed', (req) => {
    const failure = {
      url: req.url(),
      method: req.method(),
      failure: req.failure() ? req.failure().errorText : 'Unknown',
    };
    failedRequests.push(failure);
    console.warn('[Request Failed]', failure);
  });

  page.on('request', (req) => {
    if (req.url().includes('/api/')) {
      networkRequests.push({
        url: req.url(),
        method: req.method(),
        timestamp: Date.now(),
      });
    }
  });

  // 1. Navigate to app
  console.log('1. Navigating to', BASE_URL);
  await page.goto(BASE_URL, { waitUntil: 'networkidle' });

  // 2. Clear cache first via backend API to measure cold performance accurately
  try {
    const res = await page.request.post('http://localhost:8000/api/cache/clear');
    console.log('Cache cleared via API:', res.status());
  } catch (e) {
    console.warn('Could not clear cache:', e.message);
  }

  // 3. Select gearbox_assembly.step from dropdown
  console.log('2. Selecting gearbox_assembly.step...');
  const selectElem = await page.waitForSelector('header select');
  const options = await page.$$eval('header select option', (opts) =>
    opts.map((o) => ({ id: o.value, text: o.text }))
  );
  console.log('Available options:', options.map(o => o.text).slice(0, 5));

  const gearboxOption = options.find((o) => o.text.includes('gearbox_assembly.step'));
  if (!gearboxOption) {
    throw new Error('gearbox_assembly.step not found in dropdown!');
  }

  // Clear tracked API calls before triggering analysis
  networkRequests.length = 0;
  const coldStart = Date.now();
  console.log(`Selecting gearbox assembly id: ${gearboxOption.id}`);
  await selectElem.selectOption(gearboxOption.id);

  // Wait for analysis to complete (loading banner gone or score displayed)
  console.log('3. Waiting for analysis to complete (cold run, up to 180s)...');
  await page.waitForSelector('text=Overall Assembly Serviceability', { timeout: 180000 });
  const coldDurationMs = Date.now() - coldStart;
  console.log(`Cold analysis duration in UI: ${coldDurationMs} ms (${(coldDurationMs / 1000).toFixed(2)} s)`);

  const coldApiCalls = [...networkRequests];
  console.log(`Cold API calls count: ${coldApiCalls.length}`);

  // Screenshot 1: Loaded assembly
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_01_loaded.png') });
  console.log('Saved smoke_01_loaded.png');

  // Read overall score and critical issues
  const bodyText = await page.evaluate(() => document.body.innerText);
  const scoreMatch = bodyText.match(/(\d+\.?\d*)\s*\/\s*100/);
  const overallScore = scoreMatch ? scoreMatch[1] : 'Unknown';
  console.log('Extracted Overall Score:', overallScore);

  const criticalIssuesMatch = bodyText.match(/(\d+)\s+CRITICAL/i) || bodyText.match(/CRITICAL ISSUES?\s*\((\d+)\)/i);
  console.log('Critical Issue Match:', criticalIssuesMatch ? criticalIssuesMatch[0] : 'None');

  // 4. Warm performance test: select another assembly, then re-select gearbox
  console.log('4. Testing warm cache retrieval...');
  const otherOption = options.find((o) => o.id !== gearboxOption.id);
  let warmDurationMs = null;
  let warmApiCallsCount = 0;
  if (otherOption) {
    await selectElem.selectOption(otherOption.id);
    await page.waitForTimeout(1500);

    networkRequests.length = 0;
    const warmStart = Date.now();
    await selectElem.selectOption(gearboxOption.id);
    await page.waitForSelector('text=Overall Assembly Serviceability', { timeout: 30000 });
    warmDurationMs = Date.now() - warmStart;
    warmApiCallsCount = networkRequests.length;
    console.log(`Warm analysis duration in UI: ${warmDurationMs} ms (${(warmDurationMs / 1000).toFixed(2)} s)`);
    console.log(`Warm API calls count: ${warmApiCallsCount}`);
  }

  // 5. Select a component (FilterCanister)
  console.log('5. Selecting FilterCanister component...');
  const compItem = await page.waitForSelector('text="FilterCanister"', { timeout: 10000 });
  await compItem.click();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_02_component_selected.png') });
  console.log('Saved smoke_02_component_selected.png');

  // 6. Tabs verification: Access, Clearance, Sequence
  console.log('6. Checking Access tab...');
  const accessTab = await page.waitForSelector('button:has-text("Access")');
  await accessTab.click();
  await page.waitForTimeout(1000);

  // Check if freedom sphere is open by default
  const sphereBadge = await page.$('[data-testid="freedom-sphere-cone-badge"]');
  const sphereContainer = await page.$('[data-testid="freedom-sphere-container"]');
  const isSphereOpenByDefault = !!(sphereBadge || sphereContainer);
  console.log('Freedom Sphere open by default?', isSphereOpenByDefault);

  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_03_tab_access.png') });
  console.log('Saved smoke_03_tab_access.png');

  // Test opening freedom sphere
  const toggleSphereBtn = await page.$('[data-testid="toggle-removal-card-btn"]');
  if (toggleSphereBtn) {
    console.log('Opening freedom sphere via View Sphere button...');
    await toggleSphereBtn.click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_03b_sphere_open.png') });
    console.log('Saved smoke_03b_sphere_open.png');
    // Close it
    await toggleSphereBtn.click();
    await page.waitForTimeout(500);
  }

  console.log('7. Checking Clearance tab...');
  const clearanceTab = await page.waitForSelector('button:has-text("Clearance")');
  await clearanceTab.click();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_04_tab_clearance.png') });
  console.log('Saved smoke_04_tab_clearance.png');

  console.log('8. Checking Sequence tab...');
  const sequenceTab = await page.waitForSelector('button:has-text("Sequence")');
  await sequenceTab.click();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_05_tab_sequence.png') });
  console.log('Saved smoke_05_tab_sequence.png');

  // 7. Section Mode (Top, Front, tilt 30)
  console.log('9. Testing Section Mode...');
  const sectionBtn = await page.waitForSelector('[data-testid="toolbar-section-btn"]');
  await sectionBtn.click();
  await page.waitForSelector('[data-testid="compact-section-bar"]', { timeout: 5000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_06_section_top.png') });
  console.log('Saved smoke_06_section_top.png (Top plane)');

  const frontRefBtn = await page.$('[data-testid="section-ref-front"]');
  if (frontRefBtn) {
    await frontRefBtn.click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_07_section_front.png') });
    console.log('Saved smoke_07_section_front.png (Front plane)');
  }

  const tiltSlider = await page.$('[data-testid="section-tilt-slider"]');
  if (tiltSlider) {
    console.log('Setting tilt to 30 deg...');
    await tiltSlider.fill('30');
    await tiltSlider.dispatchEvent('input');
    await tiltSlider.dispatchEvent('change');
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_08_section_tilt30.png') });
    console.log('Saved smoke_08_section_tilt30.png (Tilt 30 deg)');
  }

  // Close section mode
  const closeSectionBtn = await page.$('[data-testid="section-close-btn"]');
  if (closeSectionBtn) {
    await closeSectionBtn.click();
    await page.waitForTimeout(500);
  }

  // 8. 3D Navigation: Orbit and Pan (10 drags each) & Zoom
  console.log('10. Testing Orbit (10 drags)...');
  const canvas = await page.waitForSelector('canvas');
  const box = await canvas.boundingBox();
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;

  // 10 Orbit drags with middle button
  for (let i = 0; i < 10; i++) {
    const angle = (i * Math.PI) / 5;
    const dx = Math.cos(angle) * 30;
    const dy = Math.sin(angle) * 20;
    await page.mouse.move(cx, cy);
    await page.mouse.down({ button: 'middle' });
    await page.mouse.move(cx + dx, cy + dy, { steps: 5 });
    await page.mouse.up({ button: 'middle' });
  }

  // 10 Pan drags (Shift + middle button)
  console.log('11. Testing Pan (10 drags)...');
  await page.keyboard.down('Shift');
  for (let i = 0; i < 10; i++) {
    const dx = (i % 2 === 0 ? 1 : -1) * 25;
    const dy = (i % 2 === 0 ? -1 : 1) * 15;
    await page.mouse.move(cx, cy);
    await page.mouse.down({ button: 'middle' });
    await page.mouse.move(cx + dx, cy + dy, { steps: 5 });
    await page.mouse.up({ button: 'middle' });
  }
  await page.keyboard.up('Shift');
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_09_after_orbit_pan.png') });
  console.log('Saved smoke_09_after_orbit_pan.png');

  // Wheel Zoom
  console.log('12. Testing Wheel Zoom...');
  await page.mouse.move(cx, cy);
  await page.mouse.wheel(0, -300); // Zoom in
  await page.waitForTimeout(300);
  await page.mouse.wheel(0, 200);  // Zoom out slightly
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_10_after_zoom.png') });
  console.log('Saved smoke_10_after_zoom.png');

  // Explode view
  console.log('13. Testing Explode view...');
  const explodeSlider = await page.$('input[title*="Exploded displacement"]');
  if (explodeSlider) {
    await explodeSlider.fill('0.4');
    await explodeSlider.dispatchEvent('input');
    await explodeSlider.dispatchEvent('change');
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_11_exploded.png') });
    console.log('Saved smoke_11_exploded.png');

    // Reset explode
    const resetExplodeBtn = await page.$('button[title="Reset exploded view"]');
    if (resetExplodeBtn) await resetExplodeBtn.click();
  }

  // Fit view
  console.log('14. Testing Fit-to-view...');
  const fitBtn = await page.$('[data-testid="nav-tool-fit"]');
  if (fitBtn) {
    await fitBtn.click();
    await page.waitForTimeout(1000);
  }
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'smoke_12_fit_to_view.png') });
  console.log('Saved smoke_12_fit_to_view.png');

  // Pixel non-blank verification
  const pixelCheck = await page.evaluate(() => {
    const glCanvas = document.querySelector('canvas');
    if (!glCanvas) return { hasCanvas: false, nonBlackPixels: 0 };
    const gl = glCanvas.getContext('webgl2') || glCanvas.getContext('webgl');
    if (!gl) return { hasCanvas: true, hasGL: false };
    const w = gl.drawingBufferWidth;
    const h = gl.drawingBufferHeight;
    const pixels = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    let nonBg = 0;
    // Check against background color (slate-950: rgb(2, 6, 23))
    for (let i = 0; i < pixels.length; i += 4) {
      const r = pixels[i];
      const g = pixels[i + 1];
      const b = pixels[i + 2];
      if (Math.abs(r - 2) > 15 || Math.abs(g - 6) > 15 || Math.abs(b - 23) > 15) {
        nonBg++;
      }
    }
    return {
      hasCanvas: true,
      hasGL: true,
      width: w,
      height: h,
      totalPixels: w * h,
      nonBgPixels: nonBg,
      nonBgRatio: nonBg / (w * h),
    };
  });
  console.log('Canvas WebGL pixel check:', pixelCheck);

  // Compile summary report
  const report = {
    test_timestamp: new Date().toISOString(),
    overall_score: overallScore,
    cold_analysis_duration_ms: coldDurationMs,
    warm_analysis_duration_ms: warmDurationMs,
    cold_api_calls_count: coldApiCalls.length,
    warm_api_calls_count: warmApiCallsCount,
    is_freedom_sphere_open_by_default: isSphereOpenByDefault,
    canvas_pixel_check: pixelCheck,
    failed_requests: failedRequests,
    console_errors: consoleErrors,
    console_logs_count: consoleLogs.length,
    screenshots_captured: [
      'smoke_01_loaded.png',
      'smoke_02_component_selected.png',
      'smoke_03_tab_access.png',
      'smoke_03b_sphere_open.png',
      'smoke_04_tab_clearance.png',
      'smoke_05_tab_sequence.png',
      'smoke_06_section_top.png',
      'smoke_07_section_front.png',
      'smoke_08_section_tilt30.png',
      'smoke_09_after_orbit_pan.png',
      'smoke_10_after_zoom.png',
      'smoke_11_exploded.png',
      'smoke_12_fit_to_view.png',
    ],
  };

  fs.writeFileSync(
    path.join(EVIDENCE_DIR, 'smoke_test_report.json'),
    JSON.stringify(report, null, 2),
    'utf-8'
  );
  console.log('Smoke test complete. Results written to smoke_test_report.json');

  await browser.close();
}

run().catch((err) => {
  console.error('Smoke test failed:', err);
  process.exit(1);
});
