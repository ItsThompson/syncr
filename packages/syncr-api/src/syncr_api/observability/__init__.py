"""The observability package: the duties that keep a gauge readable, and the four product metrics.

Every family declared elsewhere in this application is recorded where the thing it measures happens.
The families here cannot be, and this package exists for exactly that difference.

| What | Why it needs a duty |
|---|---|
| Source staleness, anchor counts | A gauge set when a source is polled is frozen for a source
nothing polls any more, and absent for an excluded one, which is backwards for a 24-hour alert |
| The write target's token age | A gauge set where a refresh is attempted is absent once refreshes
stop being attempted, which is when the alert has to fire |
| The four product metrics | Ratios over a period of stored rows, so nothing computes one as a side
effect of anything |

The two duties join the worker loop, which is where periodic work happens in this application. Their
figures reach Prometheus through the worker's own exposition, because a process with no HTTP surface
cannot be scraped and the api's ``/metrics`` renders the api's registry, not the worker's.
"""
