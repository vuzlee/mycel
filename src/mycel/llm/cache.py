"""Cache keyed on prompt content.

Same prompt + same model + same parameters = return the previous result without calling
again. Re-running a pipeline or debugging a report does not pay twice.
"""
