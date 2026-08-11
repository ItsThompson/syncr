"""Every repository the read histogram has to cover, discovered rather than listed.

``syncr_db_query_duration_seconds`` is installed by a base class: every repository over a
tenant-scoped table extends :class:`~syncr_api.core.repository.TenantScopedReader`, whose
``__init_subclass__`` wraps whatever methods the subclass defines. A repository read BEFORE a
tenant is known cannot extend that base, because the presented value is what supplies the scope,
so it carries the decorator itself. The hook covers whatever exists; the decorator covers whatever
someone remembered. This census is what makes the second set as reliable as the first.

**The population is the class name plus the scoped base.** Every class in this package that reads
a table is named ``*Repository``, and the walk imports every module before reading, so a repository
in a module nothing else imports is still found: keying on the name rather than on ``repository.py``
is what reaches the repositories that live in a module named for their own concern. The base is
added by inheritance rather than by name, which is what puts a read defined on the base itself under
the rule: the hook wraps a SUBCLASS, so nothing wraps the base.

**What this cannot see, stated because a census that hides its edge is worse than none.** A class
that reads a table without ``Repository`` in its name and without extending the base is outside the
population, and this package holds session-holding classes that are not repositories: a projection
pass, an expiry sweep, a horizon maintainer, for example. They read THROUGH repositories, and the
label pair the histogram carries is repository and method, so timing them would report a series
under a name no repository answers to.

**Coverage is read out of the exposition, not off ``__wrapped__``.** ``functools.wraps`` sets that
attribute, and this package has a second decorator that also uses it, so a method timed onto a
different metric presents exactly like a method timed onto this one. The registered series is what
a scraper reads and what nothing else can supply: :func:`~syncr_api.core.db_metrics.measure_reads`
resolves the child at decoration time, so the series exists before any call is made.

Every helper returns data rather than asserting, so a claim can be checked against the real
package AND against a class built to break it. A census with no positive control passes forever
once it has gone blind.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from syncr_api.core.db_metrics import READ_DURATION
from syncr_api.core.repository import TenantScopedReader
from tests.wire_census import api_modules

if TYPE_CHECKING:
    from collections.abc import Iterable

# The suffix every class that reads a table carries, which is what makes the population
# derivable at all.
REPOSITORY_SUFFIX = "Repository"

# The labels the read histogram carries, so a reading of the exposition here is keyed the way
# the metric is rather than by a spelling of its own.
REPOSITORY_LABEL = "repository"
METHOD_LABEL = "method"


def repository_classes() -> tuple[type, ...]:
    """Every repository class this package declares, in a stable order."""
    found = {
        value
        for module in api_modules()
        for value in vars(module).values()
        if isinstance(value, type)
        and value.__module__.startswith("syncr_api.")
        and (value.__name__.endswith(REPOSITORY_SUFFIX) or issubclass(value, TenantScopedReader))
    }
    return tuple(sorted(found, key=qualified))


def outside_the_hook(classes: Iterable[type]) -> tuple[type, ...]:
    """The repositories that must carry the decorator, because no base applies it for them."""
    return tuple(one for one in classes if not _is_reached_by_the_hook(one))


def _is_reached_by_the_hook(cls: type) -> bool:
    """Whether the scoped base wraps this class's reads on its behalf.

    ``__init_subclass__`` runs for a SUBCLASS, so the base itself is not reached by its own hook and
    is under the rule rather than exempt from it.
    """
    return issubclass(cls, TenantScopedReader) and cls is not TenantScopedReader


def reads(cls: type) -> tuple[str, ...]:
    """The public coroutine methods this class DEFINES, which is what the wrap covers.

    Keyed to the class's own ``__dict__`` the way the wrap is, so an inherited method is a read of
    whichever class defined it and is not asked for twice.
    """
    return tuple(
        sorted(
            name
            for name, member in vars(cls).items()
            if not name.startswith("_") and inspect.iscoroutinefunction(member)
        )
    )


def untimed(classes: Iterable[type]) -> tuple[str, ...]:
    """Every read of these classes that the histogram carries no series for.

    One reading over both mechanisms rather than trusting either. A class that extends the scoped
    base is wrapped by the hook, a class outside it is wrapped by the decorator, and nothing else
    registers a series, so this reddens whichever of the two stops working. The answer names the
    class, because the label does.
    """
    timed = timed_reads()
    return tuple(
        f"{qualified(cls)}.{name}"
        for cls in classes
        for name in reads(cls)
        if (cls.__name__, name) not in timed
    )


def timed_reads() -> frozenset[tuple[str, str]]:
    """The ``(repository, method)`` pairs the read histogram has a series for.

    Read from the metric's own samples rather than from the wrapper's attributes: a series is what
    an operator can act on, and nothing but this metric's own decorator puts one here.
    """
    return frozenset(
        (sample.labels[REPOSITORY_LABEL], sample.labels[METHOD_LABEL])
        for metric in READ_DURATION.collect()
        for sample in metric.samples
    )


def shared_labels(classes: Iterable[type]) -> tuple[str, ...]:
    """Every class name that more than one of these classes answers to.

    The histogram's ``repository`` label is the bare class name, so two repositories sharing one
    would share a series: an untimed read of the second would read as timed because the first is.
    That would make the census above pass on a class it cannot actually see.
    """
    seen: dict[str, list[str]] = {}
    for cls in classes:
        seen.setdefault(cls.__name__, []).append(qualified(cls))
    return tuple(
        f"{name} is {', '.join(sorted(holders))}"
        for name, holders in sorted(seen.items())
        if len(holders) > 1
    )


def qualified(cls: type) -> str:
    """How a class is named wherever a claim here is about one."""
    return f"{cls.__module__}.{cls.__qualname__}"
