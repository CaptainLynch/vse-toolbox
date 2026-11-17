# -*- coding: utf-8 -*-
"""VSE Toolbox v2 update kernel (runtime layer L1).

This package verifies, installs, trials and rolls back app versions. It ships
with the runtime, not with the app, so a broken app package can never break
the update path itself. Rules (do not break):

- Depend only on the standard library and ``cryptography``; never import app
  code (``core``, ``host``, ``web``, ``services``, ``plugins``).
- Switch versions only at startup; never replace files of a running version.
- Write state with a temp file + ``os.replace``.

See docs/refactor-v2/M1_PLAN.md.
"""

BOOT_API_VERSION = 1
