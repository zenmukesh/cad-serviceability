"""
Test that /api/health stays under 200 ms even while heavy analysis is actively running.
"""
import asyncio
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models.assembly import Assembly
from app.services.analysis_manager import clear_analysis_cache

async def measure_health_concurrency():
    clear_analysis_cache()
    # Pre-warm process pool to avoid one-time Windows multiprocessing spawn and import overhead
    from app.services.analysis_manager import get_process_pool, _warmup_worker
    pool = get_process_pool()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(pool, _warmup_worker)

    db = SessionLocal()
    asm = db.query(Assembly).filter(Assembly.filename == "gearbox_assembly.step").first()
    assert asm is not None
    asm_id = asm.id
    db.close()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Pre-warm ASGI app handlers
        await client.get("/api/health")

        # Start heavy analysis in background task
        analysis_task = asyncio.create_task(
            client.get(f"/api/assemblies/{asm_id}/serviceability")
        )

        # Allow child process to spawn and enter active CAD geometric computation
        await asyncio.sleep(4.0)

        # Measure 5 concurrent health check pings while CAD analysis is actively running
        health_latencies = []
        for _ in range(5):
            t0 = time.perf_counter()
            resp = await client.get("/api/health")
            dt = time.perf_counter() - t0
            assert resp.status_code == 200
            health_latencies.append(dt)
            await asyncio.sleep(0.2)

        # Await analysis completion
        analysis_resp = await analysis_task
        assert analysis_resp.status_code == 200

        max_health_ms = max(health_latencies) * 1000.0
        avg_health_ms = (sum(health_latencies) / len(health_latencies)) * 1000.0

        print(f"Health check max latency during scoring: {max_health_ms:.2f} ms")
        print(f"Health check avg latency during scoring: {avg_health_ms:.2f} ms")
        assert max_health_ms < 200.0, f"Health check exceeded 200 ms: {max_health_ms:.2f} ms"
        print("PASS: /api/health stayed under 200 ms during active scoring!")

if __name__ == "__main__":
    asyncio.run(measure_health_concurrency())
