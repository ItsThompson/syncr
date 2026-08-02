"""syncr offline learning. Never on the request path."""

# Feature extraction, the duration/time-of-day/skip fitters, learning-to-rank, the
# maturity gates, and the nightly job entrypoint land here in later slices. The
# package exists from the first commit so the offline boundary is real: this is the
# only member allowed to depend on scipy or scikit-learn.
