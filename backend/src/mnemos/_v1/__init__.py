"""v0.1 modules, quarantined pending the port to Postgres (milestone M4).

These are the working SQLite implementation: bitemporal memory store, ACL-aware
retrieval operators, the context compiler, and the naive-vs-compiled benchmark.
The logic is sound and covered by 23 tests; what changes in M4 is the storage
target (SQLite -> asyncpg + pgvector) and the home (flat module -> feature layout).

Kept intact rather than rewritten from scratch because the benchmark in `bench.py`
is the evidence for the memory/context differentiator and must keep producing
comparable numbers across the port.

Do not import from here in new code. Port, then delete.
"""
