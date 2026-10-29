# SPDX-License-Identifier: Apache-2.0
"""Einstieg für ``python -m mrt_termin_monitor``."""

import contextlib

# Vor jedem Import, der ssl-Kontexte anlegen könnte: TLS prüft dann gegen den
# Windows-Zertifikatsspeicher (deckt Proxy-Wurzeln ab und holt fehlende
# Zwischenzertifikate selbst nach). Scheitert das, bleibt certifi plus
# ``extra-ca.pem`` (fetch/http.py) – der Lauf darf daran nicht abbrechen. Ob
# truststore aktiv ist, steht im Run-Header der Log-Datei.
with contextlib.suppress(Exception):
    import truststore

    truststore.inject_into_ssl()

from mrt_termin_monitor.cli import main

raise SystemExit(main())
