"""Calendar sources, ICS ingest, the Google adapter, and the projection writer.

Two roles point in opposite directions. Many sources are read as **anchor sources**, and
exactly one is written to as a **write target**: a calendar syncr owns and reconciles
destructively. One rule keeps them from colliding, and it is enforced by this package's
service rather than by convention: a source acting as an anchor source is never the write
target, because syncr reading back its own projection would make every solve treat the
previous solve's output as immovable external commitments.

ICS is the strategic ingest path, not a fallback. It needs no OAuth verification from any
publisher and covers university timetables, holiday feeds, published Outlook, and iCloud,
so Google is one integration on top of it rather than the way in.

The adapter is a deep module on purpose. Real-world ICS is hostile, and all of that
hostility is absorbed behind a two-value return: a list of events with absolute instants,
and the sync state of the attempt that produced them.
"""
