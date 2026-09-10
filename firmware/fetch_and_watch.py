#!/usr/bin/env python3
"""Wait for the panel to come up on the native API, hold it awake, stream its
logs, press "Fetch and draw", and keep printing for --seconds.

No encryption key is configured in epaper-schedule.yaml, so none is sent.
Start this BEFORE waking the device; it retries until the API answers.

  python fetch_and_watch.py [--host epaper-13e6.local] [--wait 600] [--seconds 240]
                            [--no-press] [--no-hold]
"""
import argparse
import asyncio
import re
import time

import aioesphomeapi

ANSI = re.compile(r"\x1b\[[0-9;]*[mK]")


def ts() -> str:
    return time.strftime("%H:%M:%S")


async def connect_with_retry(host: str, wait: int) -> aioesphomeapi.APIClient:
    deadline = time.monotonic() + wait
    attempt = 0
    while True:
        cli = aioesphomeapi.APIClient(host, 6053, None)
        try:
            await asyncio.wait_for(cli.connect(login=True, log_errors=False), timeout=5)
            return cli
        except Exception as exc:  # noqa: BLE001 - device asleep / not yet on wifi
            attempt += 1
            if attempt % 10 == 1:
                print(f"{ts()} waiting for {host} ({type(exc).__name__})", flush=True)
            if time.monotonic() > deadline:
                raise SystemExit(f"gave up waiting for {host} after {wait}s")
            await asyncio.sleep(1)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="epaper-13e6.local")
    ap.add_argument("--wait", type=int, default=600, help="seconds to wait for the device to appear")
    ap.add_argument("--seconds", type=int, default=240, help="seconds to keep streaming after connect")
    ap.add_argument("--button", default="Fetch and draw")
    ap.add_argument("--no-press", action="store_true", help="only stream logs")
    ap.add_argument("--no-hold", action="store_true", help="do not switch 'Stay awake' on")
    ap.add_argument("--release", action="store_true", help="switch 'Stay awake' OFF and exit")
    args = ap.parse_args()

    cli = await connect_with_retry(args.host, args.wait)
    info = await cli.device_info()
    print(f"{ts()} connected to {info.name} ({info.esphome_version}) at {args.host}", flush=True)

    def on_log(msg: aioesphomeapi.SubscribeLogsResponse) -> None:
        raw = msg.message
        line = raw.decode("utf8", "replace") if isinstance(raw, bytes) else str(raw)
        print(ts(), ANSI.sub("", line), flush=True)

    cli.subscribe_logs(on_log, log_level=aioesphomeapi.LogLevel.LOG_LEVEL_DEBUG)

    entities, _ = await cli.list_entities_services()
    by_name = {e.name: e for e in entities}

    if args.release:
        sw = by_name.get("Stay awake")
        if isinstance(sw, aioesphomeapi.SwitchInfo):
            cli.switch_command(sw.key, False)
            await asyncio.sleep(1)
            print(f"{ts()} >>> 'Stay awake' OFF; the panel will deep-sleep at the end of its next wake cycle", flush=True)
        await cli.disconnect()
        return

    if not args.no_hold:
        sw = by_name.get("Stay awake")
        if isinstance(sw, aioesphomeapi.SwitchInfo):
            cli.switch_command(sw.key, True)
            print(f"{ts()} >>> 'Stay awake' ON (turn it off in HA or re-run with --no-hold when done)", flush=True)
        else:
            print(f"{ts()} no 'Stay awake' switch found", flush=True)

    if not args.no_press:
        btn = by_name.get(args.button)
        if isinstance(btn, aioesphomeapi.ButtonInfo):
            await asyncio.sleep(1)
            print(f"{ts()} >>> pressing {args.button!r}", flush=True)
            cli.button_command(btn.key)
        else:
            names = sorted(e.name for e in entities if isinstance(e, aioesphomeapi.ButtonInfo))
            print(f"{ts()} button {args.button!r} not found; have {names}", flush=True)

    try:
        await asyncio.sleep(args.seconds)
    finally:
        await cli.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
