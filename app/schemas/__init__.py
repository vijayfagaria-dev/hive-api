"""Input/output contracts: Pydantic request bodies + response mappers.

Request bodies validate inbound JSON/form data. Response mappers turn ORM
entities / Row tuples / service dicts into the camelCase JSON the frontend
consumes — the single place the wire format is defined.
"""
