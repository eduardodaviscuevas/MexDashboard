"""
Failure drill: simulate an outage for one series (igae) and check the failure rules.

    python verify/simulate_failure.py

Expect: igae status=error, its CSV and last_successful_fetch_utc unchanged, the top-level
last_successful_refresh_utc unchanged, last_run.status=partial, and a STALE badge on the IGAE chart.
Run `python src/fetch.py` afterwards to restore a clean state.
"""

import json, sys
sys.argv = ["fetch.py", "--no-log-file"]
from pathlib import Path
import os
os.chdir(Path(__file__).resolve().parent.parent)
sys.path.insert(0, "src")
import fetch, sources
def broken(cfg): raise sources.FetchError("simulated outage (HTTP 503)")
fetch.ADAPTERS["inegi"] = lambda cfg: broken(cfg) if cfg["id"] == "igae" else sources.fetch_inegi(cfg)
before = json.load(open("data/status.json"))
fetch.main()
after = json.load(open("data/status.json"))
b, a = before["series"]["igae"], after["series"]["igae"]
print("\nCHECKS")
print("igae status:", a["status"], "|", a["error"])
print("igae last_successful_fetch kept:", a["last_successful_fetch_utc"] == b["last_successful_fetch_utc"], a["last_successful_fetch_utc"])
print("igae attempt updated:", a["last_fetch_attempt_utc"] != b["last_fetch_attempt_utc"], a["last_fetch_attempt_utc"])
print("global last_successful_refresh unchanged:", after["last_successful_refresh_utc"] == before["last_successful_refresh_utc"], after["last_successful_refresh_utc"])
print("last_run:", after["last_run"]["status"], after["last_run"]["series_error"])
