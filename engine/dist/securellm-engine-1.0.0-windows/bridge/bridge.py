"""SecureLLM NATS Bridge — connects on-premise engine to Railway SaaS via NATS.

Subscribes to NATS subjects for this workspace, forwards HTTP requests
to the local SecureLLM engine, and publishes responses back.

Uses NATS request/reply pattern for reliable, multiplexed communication.
"""

import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone

import httpx
import nats
from nats.aio.client import Client as NATS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("securellm.bridge")

# Configuration from environment
NATS_URL = os.environ.get("NATS_URL", "nats://nats-leaf:4222")
WORKSPACE_ID = os.environ.get("WORKSPACE_ID", "")
ENGINE_URL = os.environ.get("ENGINE_URL", "http://engine:8000")
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "30"))
ENGINE_VERSION = os.environ.get("ENGINE_VERSION", "1.0.0")
INSTANCE_ID = os.environ.get("INSTANCE_ID", "")


class NATSBridge:
    """Bridges NATS messages to local SecureLLM engine HTTP calls."""

    def __init__(self):
        self.nc: NATS | None = None
        self.http_client = httpx.AsyncClient(
            base_url=ENGINE_URL,
            timeout=120.0,
        )
        self.start_time = time.time()
        self.requests_forwarded = 0
        self.errors = 0
        self._running = True
        self._heartbeat_task: asyncio.Task | None = None

    async def connect(self):
        """Connect to local NATS leaf node."""
        logger.info("Connecting to NATS at %s ...", NATS_URL)

        self.nc = await nats.connect(
            NATS_URL,
            reconnect_time_wait=2,
            max_reconnect_attempts=-1,  # Infinite reconnect
            error_cb=self._error_cb,
            disconnected_cb=self._disconnected_cb,
            reconnected_cb=self._reconnected_cb,
            closed_cb=self._closed_cb,
        )

        logger.info("Connected to NATS")

    async def _error_cb(self, e):
        logger.error("NATS error: %s", e)

    async def _disconnected_cb(self):
        logger.warning("NATS disconnected")

    async def _reconnected_cb(self):
        logger.info("NATS reconnected")

    async def _closed_cb(self):
        logger.info("NATS connection closed")

    async def subscribe(self):
        """Subscribe to request subjects for this workspace."""
        subject = f"securellm.{WORKSPACE_ID}.request"

        logger.info("Subscribing to: %s", subject)

        # Use queue group so multiple bridge instances load-balance
        await self.nc.subscribe(
            subject,
            queue="bridge",
            cb=self._handle_request,
        )

        logger.info("Bridge ready — listening for requests")

    async def _handle_request(self, msg):
        """Handle an incoming NATS request and forward to engine."""
        try:
            request = json.loads(msg.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("Invalid message: %s", e)
            if msg.reply:
                await self.nc.publish(msg.reply, json.dumps({
                    "status": 400,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"error": "Invalid request format"}),
                }).encode())
            return

        method = request.get("method", "GET").upper()
        path = request.get("path", "/")
        headers = request.get("headers", {})
        body = request.get("body", "")

        logger.info("→ %s %s", method, path)

        try:
            # Forward to local engine
            resp = await self.http_client.request(
                method=method,
                url=path,
                headers={k: v for k, v in headers.items()
                         if k.lower() not in ("host", "connection", "transfer-encoding")},
                content=body.encode("utf-8") if body else None,
            )

            response = {
                "status": resp.status_code,
                "headers": dict(resp.headers),
                "body": resp.text,
            }

            self.requests_forwarded += 1
            logger.info("← %d %s", resp.status_code, path)

        except httpx.ConnectError:
            response = {
                "status": 502,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Engine unreachable"}),
            }
            self.errors += 1
            logger.error("← 502 Engine unreachable")

        except httpx.TimeoutException:
            response = {
                "status": 504,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Engine timeout"}),
            }
            self.errors += 1
            logger.error("← 504 Timeout")

        except Exception as e:
            response = {
                "status": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": str(e)}),
            }
            self.errors += 1
            logger.error("← 500 %s", e)

        # Reply via NATS request/reply
        if msg.reply:
            await self.nc.publish(msg.reply, json.dumps(response).encode())

    async def _send_heartbeat(self):
        """Periodically publish heartbeat with engine status."""
        while self._running:
            try:
                engine_healthy = await self._check_engine_health()

                heartbeat = {
                    "type": "heartbeat",
                    "workspace_id": WORKSPACE_ID,
                    "instance_id": INSTANCE_ID,
                    "engine_version": ENGINE_VERSION,
                    "engine_healthy": engine_healthy,
                    "uptime_seconds": int(time.time() - self.start_time),
                    "requests_forwarded": self.requests_forwarded,
                    "errors": self.errors,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                await self.nc.publish(
                    f"securellm.{WORKSPACE_ID}.heartbeat",
                    json.dumps(heartbeat).encode(),
                )

            except Exception as e:
                logger.warning("Heartbeat failed: %s", e)

            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _check_engine_health(self) -> bool:
        try:
            resp = await self.http_client.get("/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def _wait_for_engine(self):
        """Wait for the local engine to be healthy."""
        logger.info("Waiting for engine at %s ...", ENGINE_URL)
        while self._running:
            if await self._check_engine_health():
                logger.info("Engine is healthy")
                return
            await asyncio.sleep(2)

    async def run(self):
        """Main entry point."""
        logger.info("SecureLLM NATS Bridge starting...")
        logger.info("  Workspace: %s", WORKSPACE_ID)
        logger.info("  Engine:    %s", ENGINE_URL)
        logger.info("  NATS:      %s", NATS_URL)

        if not WORKSPACE_ID:
            logger.error("WORKSPACE_ID not set. Exiting.")
            return

        # Wait for engine
        await self._wait_for_engine()

        # Connect to NATS
        await self.connect()

        # Subscribe to requests
        await self.subscribe()

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._send_heartbeat())

        # Keep running
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

        await self.shutdown()

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down bridge...")
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self.nc:
            await self.nc.drain()
        await self.http_client.aclose()
        logger.info("Bridge stopped")


async def main():
    bridge = NATSBridge()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(bridge.shutdown()))
        except NotImplementedError:
            pass

    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
