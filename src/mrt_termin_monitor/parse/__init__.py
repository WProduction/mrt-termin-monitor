# SPDX-License-Identifier: Apache-2.0
"""Parser: reine Funktionen Roh-Antwort → Ergebnis.

Bewusst kein Netz und kein Datei-I/O in diesem Paket: Bytes rein, Ergebnisobjekt
raus. Das hält die Parser ohne Mocks testbar und zwingt den Adapter, die
Roh-Antwort vor dem Parsen zu archivieren.
"""
