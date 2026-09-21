"""One file = one single job, done once.

A service is a link; the modules in domains/ chain those links together. So a service
must be reusable: `gather.py` serves both the report domain and the sync domain.

A service does not know which chain it sits in, nor who called it — HTTP and scheduler
look the same. Complex business rules (transforms, reasoning, building artifacts) live in
etl/, agents/, reports/; a service only calls into them.

File names are verbs, with no `_service` suffix — they are already in `services/`.
"""
