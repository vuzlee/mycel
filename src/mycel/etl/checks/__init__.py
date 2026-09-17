"""Verification after each ETL step: missing columns, unexpected nulls, row counts off
beyond the threshold.

On failure it stops and does not write to the layer above. Providers change schema without
warning all the time; without checks, gold breaks silently and the agent confidently reports
wrong numbers.
"""
