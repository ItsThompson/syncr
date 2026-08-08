"""syncr offline learning. Never on the request path.

The only member that may depend on scipy or scikit-learn. It runs as a nightly one-shot container on
a timer, is not resident, and never sits behind an HTTP surface: scipy plus scikit-learn cost
roughly 800 MB while running, which is 10% of an 8 GB host held for a process idle 99.9% of the
time.

**What is learned is not the schedule.** It is the parameters of a fixed objective: roughly 30 to 50
numbers, in a database row. That is what makes the system converge in weeks rather than years, stay
inspectable in a table, and keep the solver deterministic given a weight set.

**Every module in this package appears in one of the tables below**, which a test asserts against
the directory. The pure layer first, in the order the pipeline runs:

| Module | Holds |
|---|---|
| ``config.py`` | the priors, the prior weight, the gates, the clamps, and the restated vocabulary |
| ``facts.py`` | what the adapter loads: revisions, outcomes, edits, pins and off-plan spans |
| ``observations.py`` | what a fitter consumes: five observation kinds, each a literal |
| ``exclusions.py`` | the one statement of the off-plan rule, so two readers cannot state it twice |
| ``features.py`` | ``extract``: rows to observations, with every exclusion applied |
| ``rearrangements.py`` | the churn observation: what the user was shown and what they let stand |
| ``preferences.py`` | which edits can rank a pair, and how many predate the measurement |
| ``results.py`` | ``FitResult``, and what "not fittable" answers instead of a figure |
| ``shrinkage.py`` | the formula, the bound it puts on one outlier, and the interval |
| ``fitters/`` | the five fitters, one module and one parameter each |
| ``rank.py`` | learning to rank the seven weights, and the five refusals |
| ``gates.py`` | the per-parameter gates, and the maturity row each produces |
| ``statements.py`` | the plain-language sentence each maturity row states |
| ``artifact.py`` | the stored spelling of one appendable weight-set version |
| ``applied.py`` | what each parameter contributes to the artefact, with its gate applied |
| ``fitting.py`` | observations to one artefact: the pipeline order, and the weight fit's own gate |

Repeated-pin promotion is deliberately absent. ``syncr_domain.promotion`` holds it, because the rule
has two readers: this run reports the candidates it finds, and the weekly session raises them as a
question. The api image cannot carry scipy and so cannot depend on this package, so a rule stated
here would have needed a second statement to reach a request.

And the run, its I/O, and the container's entrypoint:

| Module | Holds |
|---|---|
| ``ports.py`` | the reader and the writer this job's I/O is stated over |
| ``job.py`` | the nightly pass over every tenant, and the report the exit code reads |
| ``metrics.py`` | the six families the run exports |
| ``storage/`` | the Postgres adapter: the spellings this job restates, and the two ends |
| ``fixtures/`` | the corpora other suites read, sized either side of every gate |
| ``entrypoint.py`` | the container's ``main``: build the adapter, run, exit |
"""
