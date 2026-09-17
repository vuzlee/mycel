"""Tools: the capabilities an agent can call.

  query_gold.py     query the gold layer via storage/postgres/
  search_docs.py    search the knowledge base via storage/vectors/
  chart.py          build a chart spec
  compute.py        percentages, growth, basic statistics

Two ways to look things up, two kinds of question: `query_gold` answers anything needing
exact figures ("Q3 revenue"), `search_docs` answers vague ones ("who discussed this").
Pick the wrong one and the agent goes looking for numbers via semantic search, then
invents one that looks about right.
"""
