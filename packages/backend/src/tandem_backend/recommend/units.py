"""Shared unit constants of the recommendation engine (one definition per conversion).

``CONTEXT_TOKENS_PER_UNIT``: rank prices added resident context as ``tokens / 2000`` cost units
(``rank.score`` → ``cost``) and prices removed resident context with the same divisor
(removal benefit), so adding and removing the same tokens are symmetric. 2000 tokens is an
uncalibrated design scale (≈ one medium skill/rules file), not a measured time cost.
There is deliberately no token → minutes constant: the time cost of resident tokens has not
been measured, so removal cards show tokens, never minutes.
"""

WEEKS_PER_MONTH = 4.345  # 52.14 weeks / 12 months: converts weekly counts to a monthly figure
CONTEXT_TOKENS_PER_UNIT = 2000
