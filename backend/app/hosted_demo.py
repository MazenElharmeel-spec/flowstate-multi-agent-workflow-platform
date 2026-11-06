"""Run the small, single-instance web demo and its local sandbox processes."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from collections.abc import Sequence

import httpx

logger = logging.getLogger("flowstate.hosted_demo")
MCP_SERVERS: tuple[tuple[str, int, str], ...] = (
    ("crm", 8001, "backend.mcp_servers.crm.server"),
    ("ticketing", 8002, "backend.mcp_servers.ticketing.server"),
    ("email", 8003, "backend.mcp_servers.email.server"),
    ("payments", 8004, "backend.mcp_servers.payments.server"),
)


async def run_command(*command: str) -> None:
    process = await asyncio.create_subprocess_exec(*command)
    code = await process.wait()
    if code != 0:
        raise RuntimeError(f"Command failed ({code}): {' '.join(command)}")


async def start_process(
    module: str,
    *,
    port: int | None = None,
    extra_env: dict[str, str] | None = None,
) -> asyncio.subprocess.Process:
    env = os.environ.copy()
    if port is not None:
        env["PORT"] = str(port)
    if extra_env:
        env.update(extra_env)
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        module,
        env=env,
    )


async def wait_for_mcp(processes: Sequence[asyncio.subprocess.Process]) -> None:
    deadline = time.monotonic() + 30
    async with httpx.AsyncClient(timeout=1) as client:
        while time.monotonic() < deadline:
            if any(process.returncode is not None for process in processes):
                raise RuntimeError("An MCP sandbox process exited during startup")
            try:
                responses = await asyncio.gather(
                    *(client.get(f"http://127.0.0.1:{port}/health") for _, port, _ in MCP_SERVERS)
                )
                if all(response.status_code == 200 for response in responses):
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.25)
    raise TimeoutError("Timed out waiting for local MCP sandbox services")


async def stop_processes(processes: Sequence[asyncio.subprocess.Process]) -> None:
    for process in reversed(processes):
        if process.returncode is None:
            process.terminate()
    for process in reversed(processes):
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()


async def run() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    processes: list[asyncio.subprocess.Process] = []
    monitor_tasks: list[asyncio.Task[int]] = []
    shutdown_task: asyncio.Task[bool] | None = None
    try:
        # Render's free plan has no separate worker service. Run the same durable
        # worker process beside the API inside this one demo web instance.
        await run_command("alembic", "upgrade", "head")
        await run_command(sys.executable, "-m", "backend.app.db.seed")

        for _, port, module in MCP_SERVERS:
            processes.append(await start_process(module, port=port))
        await wait_for_mcp(processes)

        processes.append(
            await start_process(
                "backend.app.orchestration.worker",
                extra_env={"WORKER_METRICS_PORT": "8005", "WORKER_MAX_CONCURRENCY": "1"},
            )
        )
        processes.append(
            await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                os.getenv("PORT", "10000"),
            )
        )

        loop = asyncio.get_running_loop()
        shutdown = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown.set)

        wait_tasks = {
            asyncio.create_task(process.wait(), name=f"process-{process.pid}"): process
            for process in processes
        }
        monitor_tasks.extend(wait_tasks)
        shutdown_task = asyncio.create_task(shutdown.wait(), name="shutdown")
        done, _ = await asyncio.wait(
            (*wait_tasks.keys(), shutdown_task), return_when=asyncio.FIRST_COMPLETED
        )
        if shutdown_task in done:
            return 0

        failed_process = next(wait_tasks[task] for task in done if task in wait_tasks)
        logger.error("Hosted demo child process exited with code %s", failed_process.returncode)
        return failed_process.returncode or 1
    finally:
        await stop_processes(processes)
        for task in monitor_tasks:
            task.cancel()
        if shutdown_task is not None:
            shutdown_task.cancel()
        await asyncio.gather(
            *monitor_tasks,
            *((shutdown_task,) if shutdown_task is not None else ()),
            return_exceptions=True,
        )


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run()))
    except Exception:
        logger.exception("Hosted demo failed to start")
        raise
