"""Run etl/checks/ after every transform step.

Missing columns, unexpected nulls, row counts off beyond the threshold — raise, so the
pipeline stops instead of writing to the layer above. Providers change schema without
warning all the time; without checks, gold breaks silently and the agent confidently
reports wrong numbers.
"""
