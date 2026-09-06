from __future__ import annotations

import os
from pathlib import Path

TMP = Path(__file__).resolve().parent / "_tmpdata"
TMP.mkdir(exist_ok=True)
os.environ["GEOSCOUT_DATA_DIR"] = str(TMP)
os.environ["GEOSCOUT_NCBI_MODE"] = "mock"
os.environ["GEOSCOUT_LLM_MODE"] = "mock"
os.environ["GEOSCOUT_HOST"] = "127.0.0.1"
os.environ["GEOSCOUT_ALLOW_DEMO"] = "true"
