# Capitol Pulse · A free iPhone-friendly congressional trading tracker

Capitol Pulse is a lightweight, installable **web app (PWA)**. It tracks publicly filed Congressional stock transactions, a 10-person research leaderboard ranked by *hypothetical post-disclosure returns*, stock price movement, a personal watchlist, recent-stock momentum/risk notes, and a $1,000-or-custom-amount simulator.

**Cost:** $0/month for personal, noncommercial use on GitHub Free while within GitHub's public-repository usage limits. 

## Publish it for free (one-time setup)

1. Create a free [GitHub account](https://github.com/signup) if needed.
2. Create a **public** repository named `capitol-pulse` with the default branch **main**.
3. Upload **the contents** of this project folder to the repository — not the ZIP itself. Preserve `.github/workflows/update-and-deploy.yml`, `scripts/`, `site/`, and `requirements.txt` (GitHub's **Add file → Upload files**, or use Git on a computer). This is easier from a computer for the first setup.
4. Under the repository **Settings → Actions → General**, ensure actions are enabled and that workflows have **Read and write permissions** to save a new daily snapshot. Save changes.
5. Under **Settings → Pages → Build and deployment**, set **Source: GitHub Actions**.
6. Open **Actions → Update Capitol Pulse and publish → Run workflow** (choose `main`). The first deployment runs the Python update, then publishes the `site` folder. Wait for the workflow to finish successfully; read the log if any data service fails.
7. Open `https://YOUR-GITHUB-USERNAME.github.io/capitol-pulse/` (replace the username). GitHub Pages shows the actual URL in the workflow deployment status.
8. On your **iPhone 15**, open that URL in **Safari → Share → Add to Home Screen → Add**. It opens in its own app-style view and remembers your watchlist on that device.

The schedule triggers each day at **02:17 UTC** (after the prior U.S. market close) and the site refreshes its stored JSON after the job runs. The Refresh icon rereads the most recent published file. Data **cannot** update before Congress publicly discloses a transaction, nor does daily GitHub hosting guarantee that every vendor endpoint works. A red/amber notice indicates stale or missing data. Offline, the home-screen app can show its last cached snapshot.

### One important maintenance detail

**GitHub disables scheduled workflows in public repositories after 60 days with no repository activity**. The refresh script normally makes periodic snapshot commits when successful, but don't assume those commits will always prevent inactivity suspension. If it stops updating, go to **Actions**, re-enable the workflow (if disabled), and run it manually. Also check the build log when the source price API or disclosures change. You can keep GitHub Free, and cancellation of ChatGPT Plus has *no effect*.

## How rankings work

The app ranks politicians who have at least **two verifiable purchases** filed in the chosen last 30/90/180 days. It computes an **equal-weight mean of returns on those individual reported buys**, beginning with the market close **strictly after** the filing date (to avoid assuming the public could trade before disclosure) and ending at the latest available historical closing price.

This deliberately **does not** claim to measure politicians' actual returns or portfolios. The public disclosures have amount **brackets**, not exact share counts or confirmed ongoing ownership. The app shows reported transactions as a history, never invents holdings, and does not make personal buy recommendations. Simulations exclude costs, taxes, slippage, and timing effects; the adjusted close is used when available to reduce split/dividend artifacts.

## Free data feeds and limitations

- [MacroWombat Congressional trades JSON](https://macrowombat.com/data/congress-trades.json): public House disclosures with deep links to the PDFs; 5,000 latest rows.
- [Austin Starks congressional event dataset](https://huggingface.co/datasets/austin-starks/congressional-stock-trades): normalized, versioned Senate rows from 2025–2026. This dataset includes a [federal disclosure use notice](https://huggingface.co/datasets/austin-starks/congressional-stock-trades/blob/main/LICENSE_DATA.md); use only for lawful, personal/noncommercial research. The Senate source may fail independently and is then explicitly shown as absent.
- Daily historical closing prices: Yahoo Finance chart endpoint, accessed by the optional Python price-fetch module with no key. **Not an officially guaranteed free API**: it may rate-limit, become unavailable, or impose additional use restrictions. When prices cannot be verified, returns show “—” or the last dated saved price snapshot rather than fabricated data.

Coverage is **not** every Congressional transaction since 2012. The House source keeps its latest 5,000 rows and this app analyses roughly the most recent 190 days; Senate data comes from recent year partitions. Data can be corrected and records may be duplicated across amendments; parsing suppresses identical repeated rows and filters superseded Senate versions, but cannot establish all economics of multiple identical purchases.

### Practical operation

- To investigate errors, check **Actions → latest run → Retrieve filings and price history**.
- To change refresh cadence, edit `.github/workflows/update-and-deploy.yml` (`cron`). Scheduled runs may be delayed.
- To change lookback, use the 30D/90D/180D segmented control.
- App data is saved at `site/data.json`, automatically refreshed on a successful workflow. Do not hand-edit it.
- The *watchlist* resides in iPhone Safari/local home-screen storage, not in a GitHub account. Clearing app data or reinstalling may clear it.
- If the first run fails, the site will clearly state that the initial live dataset is not available; it won't show sample people as real market results.
- GitHub Pages websites are public, and PWA installation does not involve Apple's App Store or a developer subscription.

## Files

`site/index.html`, `site/styles.css`, `site/app.js`, `site/manifest.webmanifest`, `site/sw.js`, and icons implement the standalone app. `scripts/update.py` fetches, filters, calculates, and writes `site/data.json`. `.github/workflows/update-and-deploy.yml` schedules data refresh, commits validated snapshots and deploys to GitHub Pages.

No financial advice. No paid API keys or broker connection. This personal-use research tool is unaffiliated with congressional offices, Autopilot, or GitHub.

### What appears in the stock summaries

The home page includes **Stocks on the radar**: six tickers ordered by the number of reporting members and disclosed purchases in the last 90 days. Each card provides the ticker, member count, a short observation about the last month's price movement and realized volatility, and a link to its individual transaction and custom-amount hypothetical-return simulator. “Explosive” is a **volatility description**, not a growth prediction. No ticker is recommended to buy solely because a politician reported a purchase.
