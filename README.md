# morning-edge
The Morning Edge: a one-reader morning paper, written daily by Claude

## Pullback scan

`scan/pullback_scan.py` runs the 20/50 EMA + RSI pullback scan (top 50 crypto on Crypto.com, S&P 500 from Yahoo Finance, daily bars). The workflow `.github/workflows/pages.yml` runs it after every edition push and at 07:30 SGT, inserts a "Pullback Setups" section above the footer of `index.html` and the newest edition, and deploys GitHub Pages. It never commits to `main`, so editions pushed from the laptop are unaffected. Pages source must be set to "GitHub Actions".
