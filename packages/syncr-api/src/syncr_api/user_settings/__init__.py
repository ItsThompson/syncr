"""What the user configures once: grid geometry, review cadence, zone, and travel.

Named ``user_settings`` rather than ``settings`` because ``syncr_api.core.settings``
already means the deployment's own configuration, and one word meaning two things is a
reading cost paid in every file that imports either. The route is
``/api/v1/settings``; only the Python package carries the qualifier.

The **sleep floor is not here.** It is ``minDurationMinutes`` on the sleep routine,
set through ``PATCH /api/v1/routines/{id}``, so the solver reads it from the routine it
belongs to. The Settings screen renders a labeled shortcut to that field, which is a
presentation choice and not a second home for the value.
"""
