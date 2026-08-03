"""Areas and Projects: the wedges of the allocation model, and the pushes inside them.

An Area is a hierarchical life category that carries a time budget, and it is permanent: not
completed and not archived. A Project ends, sits in exactly one Area, and declares no budget of
its own, which is what lets a time-boxed push exist without carving a new wedge out of the pie.

Areas do triple duty. They are the wedges of the allocation model, the type of a template slot,
and the category of a task, which is what allows a slot to say "one hour of Learning" and let
syncr choose the content.

Import layout, so a reader knows where to look:

| Module | Holds |
|---|---|
| ``config.py`` | the bounds, the table names, and the route paths |
| ``models.py`` | the two tables |
| ``records.py`` | the frozen views the repositories return |
| ``repository.py`` | tenant-scoped persistence, including the deal's serialization point |
| ``declarations.py`` | what a request asked to declare or change, three-valued per field |
| ``ramp.py`` | how much of the sealed pigment ramp a tenant is using |
| ``schemas.py`` | the wire shapes |
| ``service.py`` | authorization, the pigment deal, and the solve-input bump |
| ``api.py`` | the eight routes |

The budget arithmetic these tables feed is NOT here. Discretionary time, per-Area targets,
``unallocated``, and ``oversubscription`` are one computation with one implementation, in
``syncr_domain.discretionary`` and ``syncr_domain.budgets``, and ``syncr_api.budgets`` is what
reports them over one period.
"""
