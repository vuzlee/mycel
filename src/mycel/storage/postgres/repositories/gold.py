"""Business-aggregated tables. The only contract agents are allowed to read.

Changing a column here changes the contract: agents and reports break with it. Adding
columns is free; dropping one or changing its meaning needs a two-release process, like a
migration.
"""
