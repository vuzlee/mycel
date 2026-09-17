"""Call one connector in sources/, write the raw payload down to raw.

No processing, no cleaning — keeping the original means a bad transform can be re-run
from raw instead of hitting the provider again.
"""
