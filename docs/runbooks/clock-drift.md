# The host clock has drifted

## Trigger

`ClockDrifting` fires. It is a **warning**.

```
absent(node_timex_sync_status)
or node_timex_sync_status == 0
or abs(node_timex_offset_seconds) > 0.5
```

It waits **15 minutes**, so a clock being corrected does not fire it and a clock that has stopped being
corrected does.

## Why a scheduler alerts on its own clock

**The frame and the now rule are computed against the host clock.** Every one of these reads it:

| What reads the clock | What a wrong clock does |
|---|---|
| The day boundary | Yesterday's blocks appear in today's ledger, or today's are missing from it |
| Whether a block is past | The Week grid draws the now line in the wrong place and blocks read as running that have not started |
| The horizon maintainer | Advances the horizon to a week the user has not reached, or fails to advance it |
| Every staleness figure | `SourceStale` and `WriteTargetTokenExpiring` are age comparisons; a jumped clock fires or silences both |
| The debt derivation | Charges an occurrence that has not come due yet |

**Nothing fails, and everything is wrong.** That is why it is alerted rather than left to be noticed: a
drifting clock has no error, no failed request and no red container, and it produces a plan that is
internally consistent and about the wrong day.

## Why this is the thirteenth rule

Section 18 names twelve alerts and this deployment has thirteen. Section 19's failure matrix names
this one as a row of its own, "clock skew on the host: alert on NTP drift", and nothing else in the
deployment would notice. The severity is a warning rather than a critical because no data is lost and
the repair is one command.

## Read the `absent()` term first

A host with no time synchronisation at all reports **no** `node_timex_*` series, so a threshold-only
rule would be silent in the worst case. Three readings tell you which case you are in:

```
up{job="node"}                     # the exporter itself
node_timex_sync_status             # 1 when the kernel clock is synchronised, 0 when it is not
node_timex_offset_seconds          # how far off, signed
```

| Reading | Case |
|---|---|
| `up{job="node"}` is 0 | This is `database-unreachable.md`'s neighbour: the exporter is down and the clock may be fine |
| No `node_timex_*` series at all | The collector is not running, or the host has no time synchronisation configured |
| `sync_status` 0 | The clock is running free. This is the usual case |
| `offset_seconds` past half a second | It is synchronising and losing |

## The repair

```
timedatectl show                                  # NTPSynchronized, and the current offset
systemctl status systemd-timesyncd
timedatectl set-ntp true
systemctl restart systemd-timesyncd
timedatectl show                                  # NTPSynchronized=yes
```

If the host uses `chrony` instead:

```
chronyc tracking                                  # System time offset, and the reference
chronyc sources -v
systemctl restart chronyd
```

The alert clears within one scrape interval plus its 15-minute window.

## After a large correction

A clock that jumped by more than a few minutes leaves work behind it, and the order matters:

1. **Look at the Today ledger and the Week grid.** The now line is the fastest way to see whether the
   correction landed.
2. **Check the horizon.** `syncr_horizon_weeks_without_plan` should be 0. A clock that ran ahead may
   have advanced the horizon past where it belongs, which is not harmful: the weeks exist and the
   maintainer does not un-advance them.
3. **Check the two staleness alerts.** `SourceStale` and `WriteTargetTokenExpiring` are age
   comparisons, so a backwards correction can leave a source reading as fresher than it is for one
   sync interval.
4. **Do not correct data by hand.** Every derived reading, including the rotation cursor and outstanding
   debt, is re-derived from the append-only log on every read, so nothing needs repairing once the clock
   is right. A confirmation recorded against the wrong day is the one exception, and the user fixes that
   on Today.

## Not verified

- **The `node_timex_*` series have not been observed on a deployed host**, because no deployed host
  exists. The collector is enabled by default in the node exporter and Linux-only; on Docker Desktop it
  reads the virtual machine's clock rather than a host's.
- **No clock correction has been made on a running deployment**, so the four steps above are written
  from what reads the clock rather than from an incident.
