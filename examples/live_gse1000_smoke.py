"""Optional live smoke against a running local API. Requires network to NCBI via the worker."""

import asyncio

import httpx


async def main() -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=60) as client:
        health = await client.get("/api/health")
        print("HEALTH", health.status_code, health.json())
        project = await client.post(
            "/api/projects",
            json={"name": "stageA-live", "original_request": "GSE1000 live smoke"},
        )
        pid = project.json()["id"]
        run = await client.post(
            f"/api/projects/{pid}/runs",
            json={
                "mode": "manual_query",
                "manual_query": "GSE1000[Accession]",
                "budget": {"max_unique_gse": 10, "esearch_page_size": 20},
            },
        )
        rid = run.json()["id"]
        for _ in range(40):
            status = await client.get(f"/api/runs/{rid}")
            data = status.json()
            print("STATUS", data["status"], data.get("counters"))
            if data["status"] in {"completed", "partial", "failed", "cancelled"}:
                break
            await asyncio.sleep(1)
        datasets = await client.get(f"/api/runs/{rid}/datasets")
        print("DATASETS", datasets.json().get("total"), [i.get("gse") for i in datasets.json().get("items") or []])


if __name__ == "__main__":
    asyncio.run(main())
