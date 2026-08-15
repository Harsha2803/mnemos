"""The one demo warehouse this build ships.

Shared between `entrypoints/cli.py` (`datasource introspect` registers it)
and `entrypoints/api/main.py` (`Nl2SqlFlow` queries it) so the two have one
definition to agree on rather than two string literals that can drift — a
datasource registry UI is out of scope for `A3` (TRACKER §5), so this is the
only slug either place ever needs.
"""

from __future__ import annotations

DEFAULT_DATASOURCE_SLUG = "sales-warehouse"
