# PlayQueue

Lokale Warteschlange für CS2-Streams mit Twitch-Namen, OBS-Overlays und GSI-Erkennung. Chat-Kommandos werden über Streamer.bot angebunden. Das Projekt selbst verbindet sich nicht mit Twitch.

## Funktionen

- Wartende und aktuell spielende Personen verwalten; bekannte Teamspieler automatisch als spielend erkennen.
- Spiele in Folge pro Twitch-Nutzer zählen, auch beim Wechsel zwischen mehreren Steam-Konten.
- Lokale Namenssuche mit Leetspeak und Tippfehlertoleranz; Auswahl aktiver Nutzer und der Queue-Teilnehmer der letzten zwölf Stunden.
- Vorläufige Steam-Zuordnungen durch Namensvergleich und eingebautes lokales KI-Modell bestätigen oder ablehnen.
- Zufälliger Schichtwechsel mit transparentem Schuss-Overlay und Rückholung ausgeschiedener Spieler.

## Schnellstart unter Windows

1. Python installieren; für dieses Projekt Python 3.10–3.12 verwenden.
2. Projekt herunterladen und entpacken.
3. `start.bat` ausführen. Abhängigkeiten werden installiert, das KI-Modell wird im Hintergrund geladen.
4. [Adminpanel](http://127.0.0.1:5050/admin) öffnen.
5. CS2-GSI, Streamer.bot und OBS nach der [Nutzerdokumentation](docs/USER_GUIDE.md) einrichten.

**`start.bat` enthält bereits die KI.** Ollama und ein API-Key sind nicht erforderlich. Der erste Modelldownload benötigt Internet. Ohne verfügbares Modell bleibt der Namensvergleich aktiv.

Dieses Quellcodepaket enthält keine persönlichen Datenbanken, virtuelle Umgebung oder Modelldateien. Beim ersten Start entsteht eine neue `queue.db`. **Bei einem Update deine aktuelle Datenbank behalten und vorher sichern.**

## Dokumentation

- [Nutzerdokumentation](docs/USER_GUIDE.md): Installation, Bedienung, Integrationen, Updates und Fehlerbehebung.
- [Entwicklerdokumentation](docs/DEVELOPER_GUIDE.md): Architektur, Datenmodell, API, Zählregeln, Tests und GitHub-Ablauf.
- [Beiträge](CONTRIBUTING.md), [Sicherheit](SECURITY.md) und [Prüfbericht](PRUEFBERICHT.md).

## Tests

```sh
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
node tests/test_admin_search.cjs
```

Node.js wird nur für JavaScript-Tests gebraucht. GitHub Actions führt Tests auf Linux mit Python 3.10–3.12 und auf Windows mit Python 3.11 aus. Die CI-Konfiguration ist vorbereitet; ein tatsächlicher GitHub-Lauf steht nach dem Upload an.

## Betrieb und Lizenz

PlayQueue bindet an `127.0.0.1:5050` und ist für lokalen Betrieb gedacht. Eine Admin-Anmeldung und die Prüfung des GSI-Tokens sind derzeit nicht implementiert; siehe [SECURITY.md](SECURITY.md).

Für den Projektquellcode wurde noch keine Open-Source-Lizenz festgelegt. Der Eigentümer sollte vor öffentlicher Veröffentlichung eine passende `LICENSE` ergänzen. Abhängigkeiten und Modell haben eigene Lizenzbedingungen.
