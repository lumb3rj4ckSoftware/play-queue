# Nutzerdokumentation

## 1. Voraussetzungen und erster Start

Du brauchst Python 3.10–3.12, CS2 sowie für den Stream optional OBS und Streamer.bot. Installiere Python so, dass `python` im Terminal verfügbar ist. Node.js, Ollama und ein API-Key werden zum Betrieb nicht benötigt.

Entpacke das Projekt in einen eigenen, beschreibbaren Ordner. Starte `start.bat`. Der Starter wechselt in seinen Projektordner, erstellt bei Bedarf `.venv`, installiert CPU-PyTorch und die übrigen Abhängigkeiten und startet den Server. Er führt die Installationsprüfung auch bei späteren Starts aus; Internet kann dabei weiterhin erforderlich sein.

Öffne http://127.0.0.1:5050/admin. Lass das Konsolenfenster geöffnet. Beenden kannst du die Anwendung mit `Strg+C` im Konsolenfenster. Nicht mehrere Instanzen auf demselben Port starten.

Beim ersten Start entsteht `queue.db`. Sie enthält Nutzer, Queue, Steam-Verknüpfungen, Zähler und Matchhistorie. Sie ist im GitHub-Paket nicht enthalten.

### Start ohne Windows-Batchdatei

Aus dem Projektordner:

```sh
python -m venv .venv
```

Aktivierung unter Windows: `.venv\Scripts\activate.bat`; unter Linux/macOS: `source .venv/bin/activate`. Danach:

```sh
python -m pip install "torch>=2.5,<3" --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
python app.py
```

Die Anwendung immer aus dem Projektordner starten, da der Datenbankpfad relativ zum Arbeitsordner ist. Der mitgelieferte Windows-Starter macht das automatisch.

## 2. KI nutzen

Die KI ist bei `start.bat` automatisch aktiviert. `start_mit_ki.bat` ist ein zusätzlicher Kompatibilitätsstarter und nicht erforderlich.

Das Modell `Qwen/Qwen2.5-0.5B-Instruct` läuft lokal über Transformers und PyTorch auf der CPU. Beim ersten Start werden Modelldateien nach `model_cache` geladen. Die Admin-Statusanzeige informiert über Laden, Bereitschaft und Fehler. Der erste Download kann einige Zeit dauern. Optional kannst du vor dem Stream `modell_vorbereiten.bat` ausführen; dieses Skript lädt das Modell fertig und beendet sich anschließend.

Die Namen werden lokal verarbeitet. Die Bibliothek kann bei späteren Starts Modellmetadaten online prüfen. Für einen bereits vollständig heruntergeladenen Modellordner lässt sich `PLAYQUEUE_MODEL_PATH` setzen; dann wird ausschließlich aus diesem Verzeichnis geladen.

| Umgebungsvariable | Wirkung |
| --- | --- |
| `PLAYQUEUE_AI_ENABLED=0` | Nur Namensvergleich; KI deaktiviert. |
| `PLAYQUEUE_MODEL_PATH=C:\Modelle\Qwen` | Vollständiges lokales Modellverzeichnis benutzen. |
| `PLAYQUEUE_AI_MODEL=Qwen/Qwen2.5-0.5B-Instruct` | Anderes kompatibles Modell wählen; ohne Angabe gilt dieses Standardmodell. |

Beispiel für eine Windows-Eingabeaufforderung:

```bat
set PLAYQUEUE_AI_ENABLED=0
start.bat
```

Variablen gelten für den gestarteten Prozess. Eine `.env`-Datei wird nicht automatisch eingelesen. Bei Fehlern beim Laden oder bei ungültigen Modellantworten bleibt der lokale Namensvergleich als Rückfall verfügbar. Ein gültiges KI-Ergebnis mit zu geringer Sicherheit wird nicht automatisch übernommen.

## 3. CS2-GSI einrichten

Kopiere `gamestate_integration_playqueue.cfg` in den CS2-Ordner:

```text
…\Counter-Strike Global Offensive\game\csgo\cfg\
```

Starte CS2 nach dem Kopieren neu. PlayQueue muss laufen. Die Datei sendet Daten an `http://127.0.0.1:5050/gsi`. Im Adminpanel kannst du den GSI-Status und gesammelte Teamspieler beobachten.

GSI liefert abhängig von Spielzustand und Perspektive unterschiedliche Spielerdaten. PlayQueue sammelt Beobachtungen aus `player` und `allplayers` über das gesamte Match und ordnet die eigene Teamseite pro Runde zu. Eine vollständige Liste aller zehn Spieler in einem einzelnen Paket ist nicht nötig. Fehlende Daten lassen sich jedoch nicht rekonstruieren.

Das Token-Feld in der CFG wird vom Server derzeit nicht geprüft. Es schützt den Endpunkt nicht. Die Anwendung bleibt deshalb auf localhost; Details in [SECURITY.md](../SECURITY.md).

## 4. Twitch-Kommandos über Streamer.bot

Lege in Streamer.bot Aktionen mit HTTP-Aufrufen auf deinen lokalen PlayQueue-Server an. Verbinde sie beispielsweise mit deinen Chat-Kommandos. Die konkreten Kommandonamen kannst du selbst wählen.

| Aktion | HTTP-Methode und URL |
| --- | --- |
| Eintragen | GET `http://127.0.0.1:5050/api/join?user=%userName%&display=%user%` |
| Austragen | GET `http://127.0.0.1:5050/api/leave?user=%userName%` |
| Queue für Chat abrufen | GET `http://127.0.0.1:5050/api/chat-queue` |
| Overlay anzeigen | GET `http://127.0.0.1:5050/api/show-overlay` |
| Overlay ausblenden | GET `http://127.0.0.1:5050/api/hide-overlay` |

`user` ist der Twitch-Login, `display` der Anzeigename. URL-Parameter müssen korrekt URL-kodiert werden. Prüfe, dass deine Streamer.bot-Aktion diese Variablen ersetzt. `/api/chat-queue` liefert JSON; den Wert `message` anschließend mit einer eigenen Streamer.bot-Aktion in den Chat senden. PlayQueue sendet selbst keine Chatnachrichten.

## 5. Warteschlange bedienen

Im Adminpanel stehen Warteschlange und aktuell spielende Personen vor dem Schichtwechsel. Personen lassen sich manuell zwischen wartend und spielend verschieben oder entfernen. Manuelles Markieren, Entfernen und Auslosen zählen keine gespielten Matches.

Wenn ein verknüpfter Spieler im eigenen Team während eines unterstützten Live-Matches erkannt wird, verschiebt PlayQueue einen wartenden Eintrag automatisch auf spielend. Bereits entfernte/abgeschlossene Einträge werden nicht automatisch wieder in die Queue aufgenommen.

### Steam-Konten verknüpfen und suchen

Im Bereich **CS2 erkannte Spieler / Steam-Zuordnung** kannst du nach Ingame-Namen, Twitch-Namen, Anzeigenamen und SteamIDs suchen. Die Suche berücksichtigt Groß-/Kleinschreibung, Akzente, Leetspeak und kleine Tippfehler, etwa `tessa`, `XxT3ssaxX` oder `tesa`. Rein numerische Eingaben suchen nach SteamIDs. Die Suche verändert keine Verknüpfungen und benötigt keine KI.

Wähle unter **Twitch-User wählen** die passende Person und drücke **Verknüpfen**. Die Auswahl enthält alle aktiven Queue-Nutzer sowie Personen, die sich innerhalb der letzten zwölf Stunden eingetragen haben, auch wenn sie inzwischen entfernt wurden. Ältere bestehende Zuordnungen bleiben bei ihrem Konto sichtbar.

Für mehrere Steam-Konten dieselbe Twitch-Person bei jedem Konto auswählen und jeweils verknüpfen. Neue Konten ergänzen bestehende Konten. Eine SteamID kann nur einer Twitch-Person gehören. Beide Zähler gehören zur Twitch-Person und werden nicht pro Steam-Konto geführt.

### Vorläufige Vorschläge

Für aktuell spielende Personen vergleicht PlayQueue plausible Namen mit noch nicht verknüpften Teamspielern. Das gilt auch für zusätzliche Konten bereits verknüpfter Nutzer. Eindeutige Vorschläge erscheinen separat oberhalb der erkannten Spieler.

Ein Vorschlag gilt sofort vorläufig für die Erkennung und Zählung. Prüfe ihn:

- **Bestätigen:** Die Verknüpfung dauerhaft übernehmen.
- **Ablehnen:** Die vorläufige Verknüpfung entfernen, betroffene Zählungen korrigieren und dieses Paar für automatische Vorschläge sperren. Bestätigte andere Konten bleiben erhalten. Eine spätere manuelle Verknüpfung ist möglich.

Namensähnlichkeit beweist keine Identität. Bei unklaren Namen verknüpfe manuell. Fertige Hintergrund-Ergebnisse werden beim nächsten Statusabruf angewendet; ein bereits laufender Vergleich kann kurz nach Matchende noch die letzte Teilnahme korrigieren.

## 6. Spiele in Folge verstehen

Der Zähler **In Folge** ersetzt den alten Heute-Zähler. Die erste erkannte Teilnahme pro Twitch-Person und Match erhöht die Serie und den Gesamtzähler jeweils um eins. Zwei Konten derselben Person im gleichen Match zählen gemeinsam einmal. Rundenwechsel, wiederholte GSI-Pakete, Neustarts und ein Tageswechsel zählen kein zusätzliches Match.

Am Matchende wird die Serie einer nicht beteiligten Person auf null gesetzt, wenn das eigene Team vollständig gesammelt wurde: fünf eigene Spieler inklusive des Streamers in 5v5 beziehungsweise zwei in Wingman. Gegnerdaten sind dafür nicht nötig.

Bei unvollständigen Daten oder mehr unterschiedlichen eigenen SteamIDs als Teamplätzen wird kein Abwesenheitsreset durchgeführt. Casual erlaubt Teilnahmezählung, aber keinen solchen Reset; Deathmatch wird nicht gezählt. Ohne beobachtete Matches kann PlayQueue eine Pause nicht sicher feststellen.

Beim Update aus der ursprünglichen Version startet die neue Serie bei null, weil der alte Heute-Zähler keine verlässlichen Matchteilnahmen enthält. Bestehende Gesamtzähler bleiben erhalten.

## 7. Schichtwechsel und Rückholung

1. Wähle unter **Auslosbare Spieler** zwei bis vier aktuell spielende Personen.
2. Wähle wartende Nachrücker; ihre Anzahl darf die Zahl der Kandidaten nicht überschreiten.
3. Starte den Schichtwechsel. Ausgeschiedene Personen werden abgeschlossen, ausgewählte Nachrücker spielend.
4. Ist ein Nachrücker nicht verbunden, wähle ihn im Rückholbereich aus und drücke **Zufällig zurück in die Lobby**.

Die Rückholung zieht entsprechend viele noch verfügbare ausgeschiedene Personen aus dem letzten Schichtwechsel. Fehlende Nachrücker werden wieder wartend. Bereits zurückgeholte Personen werden nicht erneut gezogen. Das Programm ändert Queue-Status und Overlay; es sendet keine CS2-Lobby-Einladungen.

**Animation wiederholen** zeigt dieselbe Auslosung erneut. Es wird nicht neu gezogen. Eine Rückholung zählt kein zusätzliches Spiel.

## 8. OBS einrichten

Füge Browserquellen mit transparenter Darstellung hinzu, empfohlen 1920 × 1080:

| Quelle | URL |
| --- | --- |
| Queue/Spieler | `http://127.0.0.1:5050/overlay` |
| Schichtwechsel | `http://127.0.0.1:5050/overlay/draw` |
| Vorschau ohne Queue-Änderung | `http://127.0.0.1:5050/overlay/draw?demo=1&sound=0` |

Das Schichtwechsel-Overlay erhält die Schussanimation und hat keinen grauen flächigen Hintergrund. `sound=0` deaktiviert den Sound. Für hörbaren Sound die Audioausgabe der OBS-Browserquelle passend einstellen. Nach einem Update die Browserquelle aktualisieren, damit neue Skripte und Styles geladen werden.

## 9. Update, Sicherung und Wiederherstellung

1. PlayQueue beenden.
2. Den bisherigen Projektordner sichern, insbesondere die aktuelle `queue.db`.
3. Neue Quellcode-Dateien in den bisherigen Ordner kopieren; die aktuelle Datenbank behalten.
4. `start.bat` ausführen; Schemaerweiterungen werden automatisch angewendet.
5. Adminpanel und OBS-Browserquellen aktualisieren.

Es gibt keine automatische regelmäßige Datenbanksicherung. Für eine einfache Sicherung die Anwendung beenden und `queue.db` an einen separaten Ort kopieren. Zum Wiederherstellen die Anwendung beenden, die aktuelle Datei sichern und die gewünschte Sicherung als `queue.db` zurückkopieren. Auf passende Quellcode-/Datenbankversionen achten.

Queue leeren entfernt nicht die gespeicherte Nutzerhistorie. Keine Datenbank, Modelldateien oder persönlichen Logs auf GitHub hochladen; `.gitignore` hilft beim Ausschließen neuer Dateien.

## 10. Fehlerbehebung

| Problem | Prüfen |
| --- | --- |
| `python` nicht gefunden | Python-Installation/PATH prüfen und Terminal neu öffnen. |
| Installation bricht ab | Fehlermeldung im Konsolenfenster lesen; Internetzugang und Python-Version prüfen. |
| Port bereits belegt | Andere PlayQueue-Instanz beenden oder Port samt Integrations-URLs konsistent ändern. |
| Keine GSI-Daten | CFG-Pfad, laufenden Server und CS2-Neustart prüfen. |
| Spieler nicht als Teammitglied erkannt | GSI-Teamstatus prüfen; eigene Seite muss für die Beobachtungsrunde bekannt sein. |
| Nutzer fehlt im Auswahlmenü | Ist er aktiv oder hat er sich in den letzten zwölf Stunden eingetragen? Sonst erneut eintragen lassen. |
| Serie wird nicht zurückgesetzt | Wurde das eigene Team für dieses Match vollständig gesammelt? |
| KI lädt nicht | KI-Status, Internet und Modellpfad prüfen; manuelle Verknüpfung bleibt verfügbar. |
| OBS zeigt alte Darstellung | Browserquelle aktualisieren und korrekte URL prüfen. |

Bei einem Fehlerbericht Version, Python-Version, Spielmodus und reproduzierbare Schritte angeben. GSI-Beispiele und Logs vorher anonymisieren.
