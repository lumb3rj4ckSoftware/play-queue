# Prüfbericht – GitHub-Quellcodepaket

## Automatisierte Prüfung

- 51 Python-Regressionstests: erfolgreich.
- Vier JavaScript-Tests: erfolgreich.
- Python- und JavaScript-Syntaxprüfung: erfolgreich.
- Ausschluss persönlicher Datenbanken, Modellcache, virtueller Umgebung und generierter Logs aus der ZIP geprüft.
- `.gitignore` gegen synthetische Laufzeitdateien geprüft.
- Lokale Dokumentationslinks geprüft.

Die vorhandenen Regressionstests arbeiten mit temporären Datenbanken und simulierten GSI-/KI-/Browserobjekten. Sie decken GSI und Matchgrenzen, Serienzählung, Zuordnungsvorschläge, Schichtwechsel/Rückholung, mehrere Steam-Konten, Migration, Zwölf-Stunden-Auswahl und Namenssuche ab.

Die Tests wurden lokal ausgeführt. GitHub Actions ist für Linux/Python 3.10–3.12 und Windows/Python 3.11 vorbereitet; ein tatsächlicher Remote-CI-Lauf wurde nicht ausgeführt.

## Offene Integrationstests

Echte Qwen-Inferenz, Windows-Erstinstallation/Batchstarter, Live-CS2, OBS-Audio/Rendering und eine visuelle Browserprüfung wurden in dieser Umgebung nicht ausgeführt.

## Paket und Update

Das Paket enthält ausschließlich Quellcode, Konfiguration, Tests und Dokumentation. Es enthält keine persönlichen Datenbanken. Bei einem Update eine Sicherung erstellen und die aktuelle `queue.db` behalten. Anleitung in der [Nutzerdokumentation](docs/USER_GUIDE.md).
