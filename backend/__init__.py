"""Local FastAPI backend for the candidate-sourcing frontend.

This app is designed to run on the operator's own machine (see
CLAUDE.md/DECISIONS.md for why): classic LinkedIn scraping needs a real,
visible Playwright browser window, which only works headed and only makes
sense on the machine the operator is sitting at. It is not designed for
remote/multi-tenant hosting.
"""
