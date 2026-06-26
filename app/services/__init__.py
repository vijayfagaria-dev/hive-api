"""Business logic. Services orchestrate repositories + infra; they own
transactions only via the session passed in, and raise domain errors
(app.core.errors) that the API maps to HTTP."""
