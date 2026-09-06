# Frontend lifecycle and historical-zone semantics

## Separate UI state domains

The frontend keeps three concepts separate:

1. **Current analysis state** is the latest server-owned deterministic analysis
   for the selected symbol and timeframe. It contains indicators, structures,
   FVGs and Order Blocks.
2. **Current signal result** is the separately validated response from the
   deterministic signal endpoint: `LONG`, `SHORT`, or `NO_TRADE`.
3. **Historical terminal evidence** is immutable lifecycle history already
   present in server analysis or persistence data. In the current UI this is
   limited to FVG and Order Block lifecycle segments; there is no historical
   signal-list endpoint or client-side signal-lifecycle simulator.

Analysis zones never populate the current Signal Panel. A historical terminal
zone therefore cannot become BUY or SELL, replace a successful current
`NO_TRADE`, or act as fallback after a technical failure.

## Server-owned lifecycle

The client consumes the typed lifecycle state and event timestamps emitted by
the backend. It does not infer mitigation, fill, invalidation, expiry, signal
activation, TP/SL outcome, executed prices, PnL, or financial outcome from
chart candles, the client clock, or pixel positions.

The zone ViewModel preserves the complete lifecycle event sequence together
with the server's last-update time and the Order Block mitigation and
invalidation timestamps. These fields are retained as audit evidence even when
only the terminal event time is needed to bound the rendered segment.

Unknown lifecycle enums, a zone whose final event disagrees with its public
state, non-chronological transitions, or an event belonging to another zone
fail runtime validation. Malformed analysis is an error and cannot become a
valid overlay.

## Zone availability windows

FVG and Order Block overlays use an explicit availability window:

```text
start = FVG confirmed_at OR Order Block validated_at
end   = trusted terminal lifecycle event time, when terminal
        otherwise the current chart end
```

Terminal states are:

- FVG/IFVG: `FILLED`, `INVERTED`, `INVALIDATED`, `EXPIRED`;
- Order Block: `INVALIDATED`, `EXPIRED`.

FVG `ACTIVE`/`PARTIALLY_FILLED` and Order Block
`VALIDATED`/`MITIGATED` remain current analysis zones. An Order Block still in
`CANDIDATE` has no validated availability start and is not rendered.

Terminal zones are retained as lower-emphasis historical segments with an inset
edge, not a layout-affecting border.
They end at the immutable backend event time and receive no forward visual
padding. Adding later candles changes the chart end for active zones only; it
cannot extend, reverse, or otherwise rewrite a terminal segment.

The DOM geometry keeps live and terminal rendering separate. A terminal zone's
right edge is exactly the chart projection of its trusted terminal event; it
does not receive the live `44px` extension or the live `18px` minimum width.
Zero-width and subpixel terminal spans remain exact rather than implying later
availability. An invalid, reversed, or non-finite terminal projection is not
rendered. The terminal semantic box has zero border, padding, and minimum width;
its inset box-shadow decorates only its interior. Overflow and an inset clip
constrain its label pseudo-element to the same bounds. There is no external
outline, external shadow, or added endpoint marker. A zero-width terminal is
valid and invisible; neither its label nor a visibility minimum may imply later
availability.
Active zones and current Entry/TP/SL plans retain the documented live extension
and minimum-width presentation.

Resize, pan, or new chart data causes both endpoints to be reprojected. The
terminal endpoint remains sourced from the immutable backend event timestamp,
so the reprojected rectangle still ends exactly there.

## Actual-browser geometry regression

The existing jsdom tests validate calculated styles and projection logic; they
do not prove browser layout. `npm run test:browser` additionally mounts the real
`PriceChart` and imports the complete production `globals.css` in Chrome. Only
the chart-library projection adapter is deterministic/test-controlled. Test
fixtures stay under `frontend/tests/browser/`, outside Next.js production routes.

The browser tests measure `getBoundingClientRect()` relative to the zone layer,
including the left edge, width, and right edge. At DPR 1 and 2, the golden widths
`0`, `0.25`, `0.5`, `1`, `1.5`, `2`, and `6` CSS pixels at start `100` have zero
measured endpoint error; assertions allow at most `0.01` CSS pixels. An additional
off-grid projection explicitly allows Chrome's measured layout quantization:
less than `1/64` CSS pixel for each of left/width, and less than `2/64` for their
sum. This is browser precision, not application rounding, endpoint movement, or
a 1–2 pixel tolerance. No production outward rounding was added.

Screenshot comparisons also require no changed pixels wholly beyond the trusted
endpoint with the terminal zone visible versus hidden. The device pixel that
contains a fractional endpoint is excluded to allow ordinary edge antialiasing.
The fixture uses the production chart's solid background color so body-gradient
dithering cannot masquerade as zone paint. The assertion has no pixel-difference
allowance. Computed-style tests independently check the border, padding, minimum
width, clipping, inset shadow, outline, and transform.

The gate covers FVG/IFVG/Order Block terminals, live extension/minimum width,
future-candle redraw, pan, and a real `ResizeObserver` callback. It is included in
`npm run quality`, and therefore `scripts/quality-gates.ps1`. Chrome must be
installed. Alternatively, install Playwright's pinned Chromium with
`npx playwright install chromium` and set process-scoped
`$env:PLAYWRIGHT_CHANNEL='chromium'` before running the suite. Tests bind only to
`127.0.0.1:4178`, reject an already-used test server, and do not call market-data
providers. The JSON report and temporary browser outputs are under the ignored
`frontend/node_modules/.cache/` directory.

## Planned geometry and execution evidence

FVG and Order Block bounds are analysis geometry, not executed trade prices.
The current Signal Panel's Entry Zone, TP and SL are planned strategy geometry.
This remediation does not add historical trade execution markers.

If execution evidence is exposed in a future historical UI, requested/planned
prices and actual executed prices must remain separately labelled. The client
must consume backend `executed_entry_price`, `executed_exit_price`,
`financial_outcome`, `net_pnl`, and `net_r`; it must not derive them from candles
or assume that `TP_HIT` means profit or `SL_HIT` means exactly `-1R`.

Legacy rows without versioned execution evidence cannot be assigned an actual
exit, financial outcome, or net R by the frontend.

## Current request ownership

Every current market, analysis, and signal request is scoped to the selected
symbol/timeframe. Selection changes clear prior current state and abort the old
request. A late response cannot cross-contaminate the new selection. Refresh or
remount does not need frontend memory: zone lifecycle is rebuilt from the same
validated server payload.

A successful `NO_TRADE` remains a current deterministic result. A timeout,
provider error, or malformed payload remains a technical error. Neither state
falls back to historical zone or signal data.

This rendering contract preserves historical availability for audit. It does
not execute broker orders, reconstruct tick order, or claim exact fills.
