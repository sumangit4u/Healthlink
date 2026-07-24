"""Shared library for HealthLink microservices.

Contains the wire contract (schemas), the Gemini LLM client, settings, and
logging that are reused across the independently deployed services. Each
service image copies this package in at build time so there is a single source
of truth for the cross-service contract.
"""
