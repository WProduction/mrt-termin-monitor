# SPDX-License-Identifier: Apache-2.0
"""Adapter: verdrahten fetch und parse je Portal-Plattform.

Jedes Modul heißt wie sein ``adapter``-Wert in ``sites.yaml`` und bietet
``task_count(site)`` und ``collect(site, run_start, *, archive=None)``; der Aufrufer
lädt es über diesen Namen. ``collect`` liefert fertige Messzeilen und lässt nur
``BudgetExceededError`` und Fehler des ``archive``-Callbacks durch – jeder andere
Fehler wird eine Fehlerzeile. Den Archivfehler bewusst nicht schlucken: ohne Archiv
wäre jede spätere Fehlerzeile unbelegt, und eine volle oder gesperrte Platte trifft
ohnehin alle Institute.
"""
