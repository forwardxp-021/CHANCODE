import sys
from typing import Dict

import pytest

try:
	from tqcenter import tq
	_tq_available = True
except FileNotFoundError:
	_tq_available = False
except OSError:
	_tq_available = False

if not _tq_available:
	pytest.skip("TPythClient.dll not available in test env", allow_module_level=True)


# Basic smoke test for downloading K-line data via the TDX wrapper.
STOCK_CODE = "688318.SH"
PERIOD = "1d"
BAR_COUNT = 50


def fetch_kline() -> Dict:
	tq.initialize(__file__)
	try:
		return tq.get_market_data(
			stock_list=[STOCK_CODE],
			period=PERIOD,
			count=BAR_COUNT,
			dividend_type="none",
			field_list=[],
			start_time="",
			end_time="",
			fill_data=False,
		)
	finally:
		tq.close()


def main() -> None:
	print(f"Requesting {BAR_COUNT} bars of {PERIOD} data for {STOCK_CODE}...")
	try:
		data = fetch_kline()
	except Exception as exc:  # noqa: BLE001
		print(f"Download failed: {exc}")
		sys.exit(1)

	if not data:
		print("No data returned. Ensure the TDX client is running and the symbol is downloaded.")
		sys.exit(1)

	sample_field = next((f for f in ("Close", "Open", "High", "Low", "Amount", "Volume") if f in data), None)
	if sample_field is None:
		print(f"Fields returned: {list(data.keys())}")
		sys.exit(1)

	df = data[sample_field]
	print(f"Field '{sample_field}' shape: {df.shape}")
	print(df.tail())
	print(f"Available fields: {list(data.keys())}")


if __name__ == "__main__":
	main()
