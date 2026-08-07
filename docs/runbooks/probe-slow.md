# p99 probe duration on the request path is over 10 ms

## Trigger

`ProbeSlow` fires. It is a **warning**.

```
histogram_quantile(0.99,
  sum by (le) (rate(syncr_probe_duration_seconds_bucket{caller="request"}[30m]))) > 0.01
```

It waits **15 minutes**.

## Read the `caller` label, because it is the alert

**`caller="request"` is not a detail, it is what makes this measurable.** The plan-horizon maintainer
performs roughly **288 assemblies and probes a day** in the background, on its own 15-minute cadence.
Folding those into one series would let them either mask a request-path regression or trigger this
alert on their own, and neither reading is about what a user feels.

So this alert is about **the interactive feel of a pin** and nothing else. The maintainer's own probe
durations are a separate series on the same family, drawn on the System dashboard.

## Why 10 ms

The probe's whole justification is being sub-millisecond. It is the arithmetic that answers "what
happens if I put this here", and it runs on every candidate placement the user hovers. A p99 of 10 ms
is a thousand times the design target, which is why the threshold is generous and still meaningful: it
is not a budget, it is the point at which the design claim has stopped being true.

## Surviving capability

- **Every verdict is still correct.** It is arriving more slowly.
- Solving, projecting and confirming are unaffected.
- What has degraded is the interactive feel of a pin.

## Read this alert together with `AssemblySlow`

The two are separate on purpose, and which of them is firing tells you where to look.

| Firing | Where the cost is |
|---|---|
| `ProbeSlow` alone | The probe arithmetic itself, or the request path around it |
| `AssemblySlow` alone | The repository reads underneath. The probe's own figure would not move at all |
| Both | The assembly, almost certainly. The probe sits on top of it |

**The assembly, not the probe, is the dominant cost of a pin.** If both are firing, start at
`assembly-slow.md`.

## First checks

```
histogram_quantile(0.99, sum by (le) (rate(syncr_probe_duration_seconds_bucket{caller="request"}[30m])))
histogram_quantile(0.99, sum by (le) (rate(syncr_probe_duration_seconds_bucket{caller="worker"}[30m])))
rate(syncr_probe_duration_seconds_count{caller="request"}[30m])
```

1. **Is the request rate unusual?** A p99 computed over very few observations is noisy. Check the count
   before treating the quantile as a trend.
2. **Is the whole process slow?** If `syncr_method_duration_seconds` is up across unrelated
   repositories, this is not the probe: look at the database and at container memory on the System
   dashboard.
3. **Did the week get bigger?** The probe's cost scales with the number of commitments in the week
   being probed. A user who imported a dense timetable moves this figure legitimately.

## Still to be written

- A profile of where the probe's time goes. Nothing decomposes it below the one histogram today, so a
  regression inside the probe is visible but not attributable.
- The relationship between probe cost and week density, which would turn "the week got bigger" from a
  hypothesis into a check.
