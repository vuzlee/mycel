"""The system's entry points, split by business domain.

HTTP does not call services directly. It calls into the relevant domain's manager, and the
endpoints and business chain live inside that manager:

  managers/report/      everything to do with reports
    controller.py       HTTP endpoints — receive, validate, return
    pipeline.py         the business chain — calls services in order

Adding a domain = adding a directory here. Existing domains stay untouched.

Why split by domain rather than by technical role: changing one piece of business logic
means opening exactly one directory, instead of hopping between routes/, services/ and
pipeline/.
"""
