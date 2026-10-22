const puppeteer = require('puppeteer-core');
const path = require('path');
const fs = require('fs');

async function run() {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--window-size=1920,1200']
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1200 });

  console.log("Navigating to http://localhost:3000/stocks/SOUTHBANK...");
  await page.goto('http://localhost:3000/stocks/SOUTHBANK', { waitUntil: 'networkidle2', timeout: 30000 });

  console.log("Waiting for .stock-kpi-grid to appear...");
  await page.waitForSelector('.stock-kpi-grid', { timeout: 15000 });
  await new Promise(r => setTimeout(r, 2000));

  const outDir = path.resolve(__dirname, '../screenshots');
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

  const artifactDir = '/Users/sandeepjadhav/.gemini/antigravity-cli/brain/a3896f7c-ca09-45e3-9ab4-4a470d88b9a5/screenshots';
  if (!fs.existsSync(artifactDir)) fs.mkdirSync(artifactDir, { recursive: true });

  // 1. Overview
  console.log("Capturing Overview...");
  await page.screenshot({ path: path.join(outDir, 'southbank_overview.png'), fullPage: true });
  fs.copyFileSync(path.join(outDir, 'southbank_overview.png'), path.join(artifactDir, 'southbank_overview.png'));

  // 1b. Technicals
  console.log("Capturing Technicals...");
  await clickTab('technicals');
  await page.screenshot({ path: path.join(outDir, 'southbank_technicals.png'), fullPage: true });
  fs.copyFileSync(path.join(outDir, 'southbank_technicals.png'), path.join(artifactDir, 'southbank_technicals.png'));

  // Helper to click tab
  async function clickTab(tabId) {
    const selector = `button[data-tab="${tabId}"]`;
    const btn = await page.$(selector);
    if (btn) {
      await btn.click();
      await new Promise(r => setTimeout(r, 1200));
    } else {
      console.warn(`Tab button ${selector} not found`);
    }
  }

  // 2. Health & Diagnostics
  console.log("Capturing Health & Diagnostics...");
  await clickTab('health');
  await page.screenshot({ path: path.join(outDir, 'southbank_health.png'), fullPage: true });
  fs.copyFileSync(path.join(outDir, 'southbank_health.png'), path.join(artifactDir, 'southbank_health.png'));

  // 3. Financials & P&L
  console.log("Capturing Financials & P&L...");
  await clickTab('financials');
  await page.screenshot({ path: path.join(outDir, 'southbank_financials.png'), fullPage: true });
  fs.copyFileSync(path.join(outDir, 'southbank_financials.png'), path.join(artifactDir, 'southbank_financials.png'));

  // 4. Shareholding
  console.log("Capturing Shareholding...");
  await clickTab('shareholding');
  await page.screenshot({ path: path.join(outDir, 'southbank_shareholding.png'), fullPage: true });
  fs.copyFileSync(path.join(outDir, 'southbank_shareholding.png'), path.join(artifactDir, 'southbank_shareholding.png'));

  // 5. Quality Checklist
  console.log("Capturing Quality Checklist...");
  await clickTab('checklist');
  await page.screenshot({ path: path.join(outDir, 'southbank_checklist.png'), fullPage: true });
  fs.copyFileSync(path.join(outDir, 'southbank_checklist.png'), path.join(artifactDir, 'southbank_checklist.png'));

  // 6. AI Analyst
  console.log("Capturing AI Analyst...");
  await clickTab('ai');
  await page.screenshot({ path: path.join(outDir, 'southbank_ai.png'), fullPage: true });
  fs.copyFileSync(path.join(outDir, 'southbank_ai.png'), path.join(artifactDir, 'southbank_ai.png'));

  // 7. Full Report
  console.log("Capturing Full Report...");
  await clickTab('all');
  await page.screenshot({ path: path.join(outDir, 'southbank_full_report.png'), fullPage: true });
  fs.copyFileSync(path.join(outDir, 'southbank_full_report.png'), path.join(artifactDir, 'southbank_full_report.png'));

  // 8. Homescreen with Watchlist
  console.log("Navigating to Homescreen http://localhost:3000/...");
  await page.goto('http://localhost:3000/', { waitUntil: 'networkidle2', timeout: 30000 });
  await page.waitForSelector('.market-table', { timeout: 15000 });
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: path.join(outDir, 'homescreen_all.png'), fullPage: true });
  fs.copyFileSync(path.join(outDir, 'homescreen_all.png'), path.join(artifactDir, 'homescreen_all.png'));

  // Star a couple of stocks (e.g. first two star buttons)
  const starBtns = await page.$$('.star-btn');
  if (starBtns.length > 0) {
    await starBtns[0].click();
    if (starBtns.length > 1) await starBtns[1].click();
    await new Promise(r => setTimeout(r, 600));
  }

  // Click Watchlist Tab
  const tabBtns = await page.$$('.filter-tabs button');
  for (const b of tabBtns) {
    const text = await page.evaluate(el => el.textContent, b);
    if (text && text.includes('Watchlist')) {
      await b.click();
      await new Promise(r => setTimeout(r, 1000));
      break;
    }
  }
  await page.screenshot({ path: path.join(outDir, 'homescreen_watchlist.png'), fullPage: true });
  fs.copyFileSync(path.join(outDir, 'homescreen_watchlist.png'), path.join(artifactDir, 'homescreen_watchlist.png'));

  console.log("All screenshots captured successfully!");
  await browser.close();
}

run().catch(err => {
  console.error("Error capturing screenshots:", err);
  process.exit(1);
});
