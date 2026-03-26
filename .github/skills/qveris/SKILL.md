---
name: qveris
description: "Use when: fetching market OHLCV via QVeris API, configuring QVERIS_API_KEY, switching ChanCode data provider to QVeris, and validating A-share symbols like 601800."
---

# QVeris Data Skill

## Purpose
Use QVeris as the market data source for ChanCode.

## Environment
Set these environment variables before running:

- `QVERIS_API_KEY`: API key for QVeris authentication.
- `QVERIS_OHLCV_URL` (optional): OHLCV endpoint URL. Defaults to `https://qveris.ai/api/market/ohlcv`.

## Runtime Behavior in This Repository
- If `QVERIS_API_KEY` is present, data fetching uses QVeris API.
- If `QVERIS_API_KEY` is absent, data fetching falls back to yfinance.
- Default ticker is `601800` for GUI/CLI/demo.

## Expected QVeris Response Shape
The code accepts either:

1. `[{...}, {...}]`
2. `{"data": [{...}, {...}]}`

Each row should include:
- time key: `datetime` or `timestamp` or `date`
- `open`, `high`, `low`, `close`, `volume`

## Quick Test
Run with environment variable:

```powershell
$env:QVERIS_API_KEY = "<your-key>"
python main.py --ticker 601800 --interval 1d
```
