"""The SSE stream: one hub, one channel, and the four events a client is pushed.

| Module | Holds |
|---|---|
| ``config.py`` | the route path, the channel name, the intervals, and the four event types |
| ``envelopes.py`` | what an event carries, and the frames the wire holds |
| ``hub.py`` | the per-process fan-out: subscribe, publish, and the connection gauge |
| ``streams.py`` | the frames one connected client receives, and the heartbeat between them |
| ``channel.py`` | Postgres ``LISTEN``/``NOTIFY``: how an event crosses a process boundary |
| ``publishing.py`` | the one call a producer makes, inside its own transaction |
| ``service.py`` | the one thing a stream request authorizes |
| ``api.py`` | the one route |
| ``injection.py`` | the request-side wiring |
| ``wiring.py`` | the one factory the app factory calls |

**Events cross a process boundary, and that is why this is not just an in-memory hub.** The api runs
two uvicorn workers and the worker is a third process, so an event published by a solve that
finished
in the worker has to reach a browser connected to whichever api worker accepted its request.
Postgres
is the only thing all three share, so ``NOTIFY`` carries the event and each api process holds one
``LISTEN`` connection that feeds its own hub.

**Notification is transactional, which is a property worth having rather than an accident.**
``pg_notify`` inside a transaction delivers on COMMIT, so a supersession that rolled back publishes
nothing and a client is never told about a write that did not land.

**No replay buffer, deliberately.** A reconnecting client refetches the week, which is the source of
truth, and ``GET /operations/{id}`` answers current truth for anything it missed. A buffer would add
state to solve a problem a refetch already solves, and it would have to be per client and bounded,
which is a second delivery mechanism.
"""
