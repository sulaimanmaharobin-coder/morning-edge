# morning-edge
The Morning Edge: a one-reader morning paper, written daily by Claude

## Pullback scan

`scan/pullback_scan.py` runs the 20/50 EMA + RSI pullback scan (top 50 crypto on Crypto.com, S&P 500 from Yahoo Finance, daily bars). The workflow `.github/workflows/pages.yml` runs it after every edition push and at 07:30 SGT, inserts a "Pullback Setups" section above the footer of `index.html` and the newest edition, and deploys GitHub Pages. It never commits to `main`, so editions pushed from the laptop are unaffected. Pages source must be set to "GitHub Actions".

## The app

`app.html` (built by `scan/build_app.py` in the same workflow) puts every morning feed on one phone-friendly page: the newest edition, the top pre-breakout pullbacks, crypto watchlist setups and EMA breakout labels from Crypto.com, and jev-trader's nightly breakouts and watch levels. Add it to the home screen from the browser's share menu. The jev-trader feed needs a repository secret `JEV_TOKEN` (a fine-grained token with read-only Contents access to jev-trader); without it the app says the feed is not connected. Holdings and paper balances are never shown in the app. LTA work items live on the private Work Brief page linked from the app (`scan/app_config.json`).
