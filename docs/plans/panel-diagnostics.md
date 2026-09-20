# Panel diagnostics: the panel tells the server, the server tells Home Assistant

Status: implemented 2026-09-19. Firmware in `firmware/epaper-schedule.yaml`,
server in `panel.py`/`store.py`/`mcp_server.py`.

## The question

The wall is silent by design: it wakes about once an hour, asks for
`display.json`, usually gets a 304, and sleeps without drawing. That is the
whole point — a redraw is ~1.5 mAh against ~0.15 mAh for a wake that changes
nothing — but it means the only evidence a wake happened was a log line nobody
was watching. "Is the panel still alive, did it fetch, what did the server
say, and when did it last actually draw" had no answer short of holding the
board awake with `fetch_and_watch.py`.

## Decision 1: the server reports, not the panel. (Decided 2026-09-19.)

The obvious build is ESPHome diagnostic entities over the native API, and it
was built first — then thrown away. Two reasons.

**A deep-sleeping device is `unavailable` in Home Assistant for ~59 minutes of
every hour, so the one reading you actually want is the one you cannot get.**
"Unavailable" means asleep *or* battery flat and never coming back. Polled off
the server instead, `recent_fetch_at` older than two hours means dead, full
stop. The primary question is "is it alive", and only the server-side answer
is unambiguous.

**The panel would have had to stay awake to be heard.** A 304 wake ends a few
seconds after Wi-Fi comes up, which is not reliably long enough for HA to
notice it on mDNS and connect; publishing into a closed socket reports
nothing. Waiting for `api.connected` fixed that and cost a second or two of
radio on every wake, for data the server was about to be handed anyway.

So: the panel reports to the server, and Home Assistant polls the server,
which is up all the time.

## Decision 2: request headers on the fetch, not a POST. (Decided 2026-09-19.)

The server already records most of this. `store.note_fetch()` runs on every
request — `panel.py` calls it on the 503, 304 and 200 paths — so the fetch
record already holds when the panel asked, what was answered, and from which
address. 304-vs-200 *is* the cache hit. Only three things were missing, and
all three are things only the panel knows: **battery, last draw, wake count.**

Those ride the GET the panel already makes, as `X-Panel-Battery`,
`X-Panel-Volts`, `X-Panel-Last-Draw` and `X-Panel-Wakes`:

- **No extra request.** A POST after the draw means a second radio window
  after the 30 s refresh, on the most expensive wake there is. Headers cost
  about eighty bytes on a request that was happening anyway, and they ride the
  304 wakes too, which is where the panel spends most of its life.
- **No write route.** CLAUDE.md pins the panel endpoint as unauthenticated,
  read-only and LAN-bound. A POST handler would make it writable. A header on
  a GET leaves it read-only: the server records what it observes about a
  request it was already serving.

The headers are hearsay — anyone on the LAN can send them — so `_panel_report`
parses defensively and never raises. Out-of-range or garbled values become
`None` and the fetch is still served; sanity bounds keep nonsense out of
`status`, they do not reject the request.

**The one-wake lag is a feature.** The headers describe the wake as it starts,
so `panel_draw_at` is the *previous* draw. That makes a failure visible that
neither side could see alone: the server knows it served a 200 last hour, so
if this hour's header shows the draw time unmoved, the panel collected the
document and failed to put it on the glass. A field the panel does not send
leaves the stored value alone rather than clearing it, so a wake whose ADC
read NaN does not blank a good reading from an hour ago.

## Decision 3: one battery curve. (Decided 2026-09-19.)

The percentage used to be computed inside the display lambda for `{battery}`;
the header would have been a second copy. It now lives once, in `batt_v`'s
`on_value`, which publishes the internal `batt_pct` sensor that both the
display and the header read. `batt_pct` is `internal: true` — it exists for
the curve, not for Home Assistant. Replacing the linear 3.3 V → 0 %,
4.2 V → 100 % ramp with a real LiPo curve is now one edit.

The wake also forces `component.update: batt_v` *before* the fetch rather than
only on the redraw path, so the headers carry a live reading on a 304 wake too.

Consolidating the curve nearly introduced a nasty failure, caught in review.
The old display lambda guarded `std::isnan(v)` *before* computing anything;
the new one clamps first — and NaN compares false against everything, so
`std::min(100.0f, NAN)` returns `100.0f` and `std::max` keeps it. A failed ADC
read would have reported a **full battery** on the wall, in the header and in
Home Assistant: the worst possible direction for the one number whose job is
to warn you. The curve now returns NaN for NaN, which is what keeps the
display's `--%` fallback and the empty header reachable at all — publishing an
always-numeric `batt_pct` had quietly made both unreachable.

## Decision 4: the flashing window is paid for by the button. (Decided 2026-09-19.)

`sleep_now` waits `${flash_window}` (30 s) before deep sleep **only when the
boot button caused the wake**. The hourly timer wakes go straight back down
and cost nothing.

The first two cuts both charged every wake for a window almost no wake needs:
30 s of connected idle is ~0.8 mAh, about 20 mAh/day, several times what the
panel spends on its actual job; 5 s was ~3 mAh/day but narrow enough that the
uploader had to already be retrying when the wake landed. Both were paying an
hourly tax to be ready for something that happens twice a month.

Pressing the button *is* the "I am standing at the panel and I want it"
signal, so gate on it and the window can be as generous as it needs to be.
`on_boot` reads `esp_sleep_get_wakeup_cause()` — `esp_sleep.h` arrives with
deep_sleep's own header — and the button's `on_press` sets the same flag for
a press on a board that is already up. The flag is never cleared inside
`wake_cycle`, so a press is still honoured if a second cycle runs before the
board sleeps.

A cold boot reports `ESP_SLEEP_WAKEUP_UNDEFINED` and is deliberately **not**
counted as a press. It is tempting — a power-on is also a human holding the
device — but a brownout loop on a flat battery reports the same thing, and
would then hold the board open for 30 s on every restart, which is precisely
when it can least afford it. Press the button after a power-on.

On a redraw the hold is 30 s on top of an already 35 s wake. Left as is: it is
a deliberate press either way, and a rule with no exceptions is worth more
than the half a milliamp-hour a month that gating it on the 304 would save.

### Three things the hold broke, all of them because it made `sleep_now` slow

On `origin/main` `sleep_now` ran to completion in one loop iteration. A 30 s
delay inside it turns it into a script with a lifetime, and three things
assumed it did not have one.

**It would deep-sleep through a second cycle.** `sleep_now` is `mode: single`,
so the `script.execute: sleep_now` at the end of a *second* `wake_cycle` is
silently dropped while the first hold is still running — and the first hold
then expires mid-refresh and forces a sleep. Press the button, get a 304,
press it again, and the redraw it triggers is cut off part-way with the wall
left half-drawn and `dl_shown_id` unchanged. Pressing the button twice is
exactly what someone standing at the panel does. `wake_cycle` now opens with
`script.stop: sleep_now`: the newest cycle owns the sleep.

**`deep_sleep.enter` is forced.** It calls `begin_sleep(true)`, which ignores
`deep_sleep.prevent`, so `ota: on_begin: deep_sleep.prevent` only ever covered
the component's own `run_duration`. `sleep_now` waits on an `ota_active`
global instead. (This one predates the hold; it just could not bite while the
window was zero-length.)

**`deep_sleep.allow` is not OTA's to give.** `prevent`/`allow` is a single
shared flag, and the "Stay awake" switch holds the same one. The first cut of
the `on_error` handler allowed unconditionally, so a failed upload with "Stay
awake" on would drop the board into an hour of sleep with the switch still
showing on — and because `deep_sleep` latches a deferred sleep while
prevented, it would go down on the very next loop iteration. `on_error` now
allows only when the switch is off, and re-arms the hold so a failed upload
leaves a window to retry in rather than an hour's wait.

## Reading it

`status` and `/healthz` both carry the fields. Healthy is `recent_fetch_at`
within the hour, `recent_fetch_status` 304, `panel_draw_at` much older, and
`hash` equal to what was last published.

| Reading | Means |
|---|---|
| `recent_fetch_at` hours old | The panel is not waking. Battery, Wi-Fi, or a hang. |
| `recent_fetch_status: 200` repeatedly, content unchanged | The ETag is moving when the content is not — see "Change detection" in SPEC.md. |
| a 200 served, `panel_draw_at` unmoved next wake | Fetched fine, failed to draw. |
| `panel_wakes` jumping by more than one per hour | Something is rebooting it — the boot button, a brownout. |
| `panel_battery` falling faster than the budget predicts | Usually "Stay awake" left on, or a lot of boot-button presses, each buying a `${flash_window}` hold. |

## The Home Assistant side

A REST sensor against `/healthz`, which the panel listener already serves
unauthenticated on the LAN. No template mirrors, no unavailability gap,
because the thing being polled is the server and not the panel:

```yaml
# configuration.yaml
#
# Every template starts by resolving the display out of the list, because
# /healthz lists only *published* displays: before the first set_display the
# list is empty, and `| first` on an empty sequence is a template error, not a
# null. `availability` does not spare `value_template` from being rendered, so
# both have to survive a null of their own.
rest:
  - resource: http://172.17.247.125:8080/healthz
    scan_interval: 300
    sensor:
      - name: Panel last fetch
        unique_id: panel_last_fetch
        device_class: timestamp
        availability: >
          {% set d = value_json.displays | selectattr('name', 'eq', 'default') | list %}
          {{ d | length > 0 and d[0].recent_fetch_at is not none }}
        value_template: >
          {% set d = value_json.displays | selectattr('name', 'eq', 'default') | list %}
          {{ (d[0].recent_fetch_at | as_datetime)
             if d and d[0].recent_fetch_at is not none else '' }}
      - name: Panel last draw
        unique_id: panel_last_draw
        device_class: timestamp
        availability: >
          {% set d = value_json.displays | selectattr('name', 'eq', 'default') | list %}
          {{ d | length > 0 and d[0].panel_draw_at is not none }}
        value_template: >
          {% set d = value_json.displays | selectattr('name', 'eq', 'default') | list %}
          {{ (d[0].panel_draw_at | as_datetime)
             if d and d[0].panel_draw_at is not none else '' }}
      - name: Panel battery
        unique_id: panel_battery
        device_class: battery
        unit_of_measurement: "%"
        availability: >
          {% set d = value_json.displays | selectattr('name', 'eq', 'default') | list %}
          {{ d | length > 0 and d[0].panel_battery is not none }}
        value_template: >
          {% set d = value_json.displays | selectattr('name', 'eq', 'default') | list %}
          {{ d[0].panel_battery if d and d[0].panel_battery is not none else '' }}
      - name: Panel fetch status
        unique_id: panel_fetch_status
        availability: >
          {% set d = value_json.displays | selectattr('name', 'eq', 'default') | list %}
          {{ d | length > 0 and d[0].recent_fetch_status is not none }}
        value_template: >
          {% set d = value_json.displays | selectattr('name', 'eq', 'default') | list %}
          {{ d[0].recent_fetch_status if d and d[0].recent_fetch_status is not none else '' }}
```


`recent_fetch_at` and `panel_draw_at` are unix floats, which `as_datetime`
turns into the tz-aware value `device_class: timestamp` wants. The alert worth
having is the one the native-API build could not express at all:

```yaml
automation:
  - alias: Panel stopped waking
    triggers:
      - trigger: template
        # `not has_value(...)` comes first on purpose. If the display-mcp host
        # is down the sensor is `unavailable`, and `'unavailable' | as_datetime`
        # is None, so any arithmetic on it raises and the trigger would never
        # fire — in exactly the case the alert exists for. `for` keeps an HA
        # restart or one missed poll from crying wolf.
        value_template: >
          {{ not has_value('sensor.panel_last_fetch')
             or now() - (states('sensor.panel_last_fetch') | as_datetime)
                > timedelta(hours=3) }}
        for: "00:10:00"
    actions:
      - action: notify.persistent_notification
        data:
          message: >
            E-paper panel has not fetched since
            {{ states('sensor.panel_last_fetch') }}
```

## Left out

- **A dedicated `/panel.json`.** `/healthz` already carries the fetch record
  per display, so HA gets a flatter object at the cost of a route nothing else
  needs. The `selectattr` in each template is the price of not adding one.
- **Fetch duration.** `response->duration_ms` is right there in `on_response`
  and would show a slow server before it becomes a failed one. Four lines
  whenever it is wanted.
- **Wake reason** (timer vs. boot button). `esp_sleep_get_wakeup_cause()` would
  say; `panel_wakes` jumping by more than one an hour already implies it.
- **History.** The fetch record keeps only the most recent reading. Battery
  over weeks is HA's recorder's job, not this file's.
