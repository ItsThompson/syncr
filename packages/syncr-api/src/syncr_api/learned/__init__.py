"""The read side of the learning layer: versioned weight sets and their maturity.

The fitters themselves live in ``syncr-learning``, which is offline and never imported by a
request path. This package holds the row they write and the row the solve path reads.
"""
