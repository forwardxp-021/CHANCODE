import os, json, datetime, pandas as pd, requests
base = os.getenv("QVERIS_API_BASE","https://qveris.ai/api/v1").rstrip("/")
key = os.environ["QVERIS_API_KEY"]
headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
search_payload = {"query": "China A-share OHLCV historical K line 601800", "limit": 12}
print("searching...")
s = requests.post(f"{base}/search", json=search_payload, headers=headers, timeout=15)
print("search status", s.status_code)
if s.status_code >= 400:
    print("search body", s.text[:500])
    raise SystemExit(f"search failed: HTTP {s.status_code}")
body = s.json()
print("search keys", list(body.keys()))
tools = body.get("tools") or body.get("results") or body.get("data") or []
print('tools found', len(tools))
for t in tools:
    print('tool', t.get('tool_id') or t.get('id'), t.get('name'))
search_id = body.get("search_id") or body.get("id")
tool_id = None
for t in tools:
    tid = str(t.get("tool_id") or t.get("id") or "")
    name = str(t.get("name") or "")
    if "history_quotation" in tid or "history_quotation" in name:
        tool_id = tid
        break
print("picked tool", tool_id)
if not tool_id:
    raise SystemExit("no history tool")
start = (datetime.date.today() - datetime.timedelta(days=240)).strftime("%Y-%m-%d")
end = datetime.date.today().strftime("%Y-%m-%d")
params = {"codes": "601800.SH", "startdate": start, "enddate": end, "interval": "D", "indicators": "common"}
exec_payload = {"search_id": search_id, "parameters": params, "max_response_size": 20480}
print("executing...")
e = requests.post(f"{base}/tools/execute", params={"tool_id": tool_id}, json=exec_payload, headers=headers, timeout=30)
print("exec status", e.status_code)
print("exec text head", e.text[:500])
res = e.json()

full_url = None
if isinstance(res, dict):
    full_url = res.get("full_content_file_url")
    if isinstance(res.get("result"), dict):
        full_url = res["result"].get("full_content_file_url") or full_url

rows = None
if isinstance(res, dict):
    rows = res.get("result") or res.get("data") or res.get("rows") or None
if rows is None:
    rows = res
if isinstance(rows, dict) and "items" in rows:
    rows = rows["items"]

if (not isinstance(rows, list) or not rows) and full_url:
    print("fetching full content", full_url)
    fr = requests.get(full_url, timeout=30)
    text = fr.text
    try:
        payload = fr.json()
    except Exception:
        payload = None
    if payload is not None:
        if isinstance(payload, dict):
            rows = payload.get("data") or payload.get("rows") or payload.get("result") or payload.get("items")
        elif isinstance(payload, list):
            rows = payload
    if (not rows) and "," in text and "\n" in text:
        try:
            df = pd.read_csv(pd.compat.StringIO(text))
            rows = df.to_dict(orient="records")
        except Exception:
            pass

# Flatten nested list payloads like [[{...}]].
if isinstance(rows, list) and rows and all(isinstance(x, list) for x in rows):
    rows = rows[0]

if not isinstance(rows, list):
    raise SystemExit("no row list")
if not rows:
    raise SystemExit("empty rows")
records = []
for r in rows:
    if not isinstance(r, dict):
        continue
    records.append(r)
print("records", len(records))
df = pd.DataFrame(records)
print(df.head())
df.to_csv("qveris_601800_daily.csv", index=False)
print("saved csv", len(df))
