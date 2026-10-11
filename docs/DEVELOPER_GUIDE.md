# Entwicklerdokumentation

## Projekt und Entwicklungsumgebung

PlayQueue ist eine lokale Flask-Anwendung mit SQLite, browserseitigem JavaScript und optionaler lokaler Transformers-Inferenz. Kein Frontend-Build, Twitch-SDK oder Node-Server ist nötig. Python 3.10–3.12 ist die vorgesehene Testmatrix; Node.js 22 wird für JavaScript-Tests verwendet.

Für Entwicklung ohne echtes Modell:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate.bat
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
node tests/test_admin_search.cjs
```

Für Appbetrieb mit Modell zusätzlich CPU-PyTorch und `requirements.txt` installieren, siehe [Nutzerdoku](USER_GUIDE.md). Ohne KI lassen sich unter Bash `PLAYQUEUE_AI_ENABLED=0 python app.py` oder unter Windows `set PLAYQUEUE_AI_ENABLED=0` und anschließend `python app.py` verwenden. Modellimporte erfolgen erst beim Laden.

`python app.py` aus dem Projektordner startet Initialisierung, Modellvorbereitung und Server. `DB_PATH = Path("queue.db")` ist relativ zum aktuellen Arbeitsverzeichnis. `APP_PORT = 5050` ist eine Konstante, keine Umgebungsvariable. Importieren von `app` allein initialisiert die Datenbank nicht: eigene Test-/WSGI-Einstiegspunkte müssen `init_db()` ausdrücklich aufrufen. Der bisherige Startpfad ist ein einzelner lokaler Prozess, kein produktives Mehrprozess-Deployment.

## Quellcode-Struktur

| Datei/Bereich | Verantwortung |
| --- | --- |
| `app.py` | Flask-Routen, Queue-Operationen, Datenbankbasis, Auslosung und JSON-Zustand. |
| `gsi_engine.py` | Matchgrenzen, Beobachtungen, Teamzuordnung, Teilnahmeledger, Serien und Vorschläge. |
| `steam_links.py` | Mehrere Steam-Konten, Migration und kompatible Hauptkontofelder. |
| `alias_ai.py` | Lokales Modell, Status, Laden und Konfidenzantworten. |
| `templates/` | Adminpanel, Queue-Overlay, Draw-Overlay und gemeinsames Draw-Markup. |
| `static/admin.js` | Adminaktionen, Polling, Zuordnungen und Auslosungsbedienung. |
| `static/name_search.js` | Browserseitiger toleranter Namens-/SteamID-Abgleich. |
| `static/overlay.js`, `static/draw_overlay.js` | Overlayzustand und Animation. |
| `static/*.css` | Admin-/Queue-/Draw-Darstellung. |
| `tests/` | Python-Regressionstests und JavaScript-Tests mit simuliertem Browserumfeld. |
| `.github/workflows/ci.yml` | Linux-/Windows-Tests ohne echte Modelldateien. |

## Datenmodell

SQLite-Verbindungen verwenden `sqlite3.Row`. `init_db()` ergänzt Tabellen und fehlende Spalten idempotent, anschließend initialisieren GSI- und Steam-Module ihre Erweiterungen. Neue Migrationen müssen vorhandene Daten erhalten und auch bei wiederholtem Start funktionieren. Vor Migrationen eine Kopie einer gestoppten Datenbank sichern; Tests nie gegen die persönliche `queue.db` laufen lassen.

| Tabelle | Zweck |
| --- | --- |
| `users` | Twitch-Identität, Anzeigename, Gesamtzähler, `in_a_row` und historische Hauptkontofelder. |
| `queue` | Eintrag mit Status `waiting`, `playing` oder `done` und Zeitstempeln. |
| `steam_accounts` | Maßgebliche Steam-Zuordnungen; SteamID eindeutig, viele Konten pro Twitch-Nutzer. |
| `detected_players` | Erkannte Steam-Spieler und letzte Beobachtungsdaten. |
| `app_state` | Persistierter UI-/GSI-Zustand als Schlüssel/Wert, teils JSON. |
| `rotation_draws` | Auslosung, Spieler-Snapshots und Animationszustand. |
| `matches` | Matchidentität, Abschluss und Vollständigkeit. |
| `match_observations` | Spielerbeobachtung je Match, SteamID und Runde. |
| `match_team_rounds` | Bekannte eigene CT-/T-Seite je Match und Runde. |
| `match_players` | Teilnahmeledger, eindeutig nach Match und Twitch-Namen. |
| `match_user_baselines` | Serienstand vor dem Match für spätere Korrekturen. |
| `steam_proposals` | Vorläufige/bestätigte/abgelehnte Zuordnungsvorschläge. |
| `rejected_links` | Für automatische Zuordnung gesperrtes Steam-/Twitch-Paar. |

`steam_accounts` ist die führende Zuordnung, nicht `users.steam_id`. Alte Felder und Trigger bleiben zur Kompatibilität erhalten. Bereits gespeicherte Konten werden migriert; ein neues Konto darf kein anderes Konto desselben Nutzers löschen. Zwei erkannte Konten derselben Person im gleichen Match führen aufgrund des Teilnahmeledgers zu genau einer Teilnahme.

Queue-Entfernung ist ein Statuswechsel. Die Zwölf-Stunden-Auswahl liest die letzte Eintragung pro Twitch-Nutzer und kombiniert sie mit aktiven Einträgen. Dadurch bleiben kürzlich entfernte Nutzer auswählbar. Zeitstempel werden durch `now_iso()` erzeugt; zwölf Stunden sind ein rollierendes Fenster, kein Kalendertag.

Die alten Heute-Felder und Hilfsfunktionen bestehen noch aus Kompatibilitätsgründen. Neue Logik verwendet `in_a_row`; manuelle Queue-Aktionen dürfen die alten Zählhelfer nicht zur Matchzählung wieder einführen.

## GSI- und Zählregeln

`POST /gsi` extrahiert Spieler aus `player` und `allplayers`, speichert erkannte Spieler und übergibt das Paket an die GSI-Engine. `provider.steamid` identifiziert den sendenden Client. Dessen eigene Seite sowie bekannte Teammates können die Teamseite einer Runde verankern. Gespeicherte Beobachtungen werden mit der Seite ihrer jeweiligen Runde verglichen; ein späterer Seitenwechsel darf sie nicht umdeuten.

Unbekannte Seiten werden nicht geraten. Sobald die Seite einer Runde feststeht, lassen sich frühere Beobachtungen dieser Runde nachträglich zuordnen. Beobachtungen und Matchstatus bleiben nach einem Neustart erhalten.

Neue Matches werden unter anderem an Gameover/Warmup → Live, Map-/Provider-/Moduswechsel oder Runde null mit beiden Scores null erkannt. Halbzeit und Verlängerung mit bestehendem Score bleiben im selben Match.

Unterstützt sind `competitive`, `premier`, `scrimcomp5v5`, `scrimcomp2v2` und `casual`. Die ersten drei Modi benötigen fünf eigene SteamIDs für einen sicheren Abwesenheitsreset, Wingman zwei. Casual hat keine hier festgelegte feste Teamgröße und erhält keinen solchen Reset. Deathmatch ist ausgeschlossen.

Bei der ersten verknüpften eigenen Live-Teilnahme wird `(match_id, twitch_name)` ins Ledger geschrieben, `in_a_row` und `played_count` erhöht und ein wartender Queue-Eintrag auf spielend gesetzt. Fertige Einträge werden nicht automatisch wieder aktiviert. Mehrere Konten, Heartbeats und Rundenwechsel dürfen keine weiteren Ledger-Zeilen für denselben Nutzer erzeugen.

Am Matchende werden Serien fehlender Nutzer nur bei vollständigem eigenem Team zurückgesetzt. Vollständig bedeutet exakt die erwartete Anzahl unterschiedlicher eigener SteamIDs über das Match; Gegner sind nicht erforderlich. Weniger oder mehr SteamIDs erlauben keinen sicheren Abwesenheitsreset. Ein Tageswechsel ist kein Resetgrund.

`GET /api/state` ist technisch kein rein lesender Endpunkt: Er startet eine unmittelbare SQLite-Transaktion und ruft `gsi_engine.refresh()` auf. Dabei können fertig gewordene KI-Ergebnisse, Zuordnungen und Teilnahmekorrekturen übernommen werden. Dies bei Caching, Mocking und zukünftigen API-Umbauten berücksichtigen.

## Namenssuche und KI

Die UI-Suche läuft rein lokal in `name_search.js`: Normalisierung von Groß-/Kleinschreibung, Akzenten, Leetspeak und dekorativem `xx`, Teilstrings und Ähnlichkeit für Namen ab drei Zeichen. Numerische Eingaben werden als SteamID-Suche behandelt. Der Suchfilter muss die ausgewählte Zuordnung und fokussierte Eingabeelemente bei Statusaktualisierungen erhalten.

Automatische Vorschläge beziehen sich auf aktuell spielende Twitch-Nutzer und ungebundene eigene Teamkonten. Bereits gebundene Nutzer können zusätzliche Konten erhalten. In `gsi_engine.py` beginnt der Modellvergleich ab lexikalischer Ähnlichkeit 0,5. Ein Worker verarbeitet Modellaufträge; die gleichzeitig offenen Aufträge sind begrenzt. Ein gültiges Modellresultat unter 0,9 wird verworfen. Vorschläge benötigen mindestens 0,88 und einen Abstand von 0,12 zu konkurrierenden Zuordnungen in beiden Richtungen. Diese Werte sind Heuristiken, keine statistisch kalibrierten Identitätswahrscheinlichkeiten.

`alias_ai.py` lädt standardmäßig `Qwen/Qwen2.5-0.5B-Instruct`, CPU/float32, zwei Torch-Threads, ohne Remote-Code und mit Safetensors. Modellpfad/Name und Aktivierung werden über die in der Nutzerdoku beschriebenen Umgebungsvariablen konfiguriert. Ein expliziter vorhandener Modellordner wird lokal geladen. Fehler oder ungültige Ausgaben erlauben den lexikalischen Rückfall; valide niedrige Konfidenz darf nicht zu einer KI-Bestätigung werden.

Vorläufige Zuordnungen gelten sofort. Bestätigung ändert den Kontostatus. Ablehnung entfernt nur die betroffene vorläufige Verbindung, sperrt das Paar und korrigiert Ledger/Zähler. Wenn ein anderes bestätigtes Konto dieselbe Teilnahme belegt, muss sie erhalten bleiben. Nach Gameover können bereits begonnene Jobs noch berücksichtigt werden; für neu ausgewählte Personen werden aus dem geschlossenen Match keine neuen Vergleiche begonnen.

## Auslosung

`secrets.SystemRandom` wählt ausgeschiedene Kandidaten. Es werden zwei bis vier aktuelle Personen und höchstens entsprechend viele wartende Nachrücker ausgewählt. Snapshots und Ergebnis werden gespeichert. Replay verändert nur die Animationsrevision; es lost nicht erneut aus.

Eine Rückholung bezieht sich auf den letzten Draw und konkrete fehlende Nachrücker. Sie zieht dieselbe Anzahl noch verfügbarer ausgeschiedener Personen, setzt fehlende Nachrücker auf wartend und Rückkehrer auf spielend. Bereits zurückgeholte Personen und doppelte aktive Twitch-Einträge werden ausgeschlossen. `draw_id` und Animationsrevision schützen vor veralteten Aktionen; Konflikte können HTTP 409 liefern. Queue-Änderungen sind keine CS2-Lobbyaktionen und zählen keine Matches.

## HTTP-Schnittstellen

Die API ist lokal und ohne Anmeldung. JSON-Aktionen mit `Content-Type: application/json` senden. IDs von Queue-Einträgen und Draws aus dem aktuellen Zustand verwenden. Einige bestehende integrationsfreundliche GET-Routen verändern den Zustand.

| Methode | Route | Eingabe / Ergebnis |
| --- | --- | --- |
| GET | `/`, `/admin` | Weiterleitung beziehungsweise Adminseite. |
| GET | `/overlay`, `/overlay/draw` | OBS-Seiten; Draw optional `demo=1`, `sound=0`. |
| GET | `/api/join` | Query `user`, optional `display`; Queue-Eintragung. |
| GET | `/api/leave` | Query `user`; Austragen. |
| GET | `/api/state` | Zustand plus Verarbeitung fertiger Hintergrund-Ergebnisse. |
| GET | `/api/chat-queue` | JSON mit `ok` und `message`. |
| GET | `/api/show-overlay`, `/api/hide-overlay` | Overlay-Sichtbarkeit verändern. |
| POST | `/api/remove/<queue_id>` | Queue-Eintrag abschließen. |
| POST | `/api/waiting/<queue_id>` | Eintrag wartend setzen. |
| POST | `/api/playing/<queue_id>` | Eintrag spielend setzen. |
| POST | `/api/finish-playing` | Aktuelle spielende Einträge abschließen. |
| POST | `/api/clear-queue` | Queue leeren/abschließen. |
| POST | `/api/clear-detected` | Erkannte-Spieler-Liste leeren. |
| POST | `/api/link-steam` | `twitch_name`, `steam_id`, `steam_name`; Konto zuordnen. |
| POST | `/api/proposal` | `steam_id`, `action`: `confirm` oder `reject`. |
| GET | `/api/draw/state` | Gespeicherter Drawzustand. |
| POST | `/api/draw/start` | `candidate_ids`, `challenger_ids`: Arrays mit Queue-IDs. |
| POST | `/api/draw/replay` | Gespeicherten Draw erneut anzeigen. |
| POST | `/api/draw/hide` | Optional `draw_id`, `animation_revision` als Aktualitätsprüfung. |
| POST | `/api/draw/return` | `draw_id`, `missing_ids`: fehlende Nachrücker zurücksetzen und Rückkehrer ziehen. |
| POST | `/gsi` | CS2-GSI-JSON mit Provider, Map, Player und/oder Allplayers. |

`/api/state` enthält `ok`, `overlay_visible`, `queue`, `waiting`, `playing`, `overlay_playing`, `detected_players`, `link_users`, `draw`, `proposals`, `gsi_status` und `ai_status`. Nutzer-/Spielerobjekte können `steam_accounts` mit mehreren Konten enthalten. Nicht ausschließlich auf das historische einzelne `steam_id`-Feld verlassen.

Ungültige Anfragen können 400, fehlende Einträge 404 und Konflikte/veraltete Aktionen 409 liefern; konkrete Antwortstruktur im jeweiligen Handler prüfen. Beispiel einer manuellen Verknüpfung mit ausschließlich synthetischen Daten:

```json
{"twitch_name":"beispieluser","steam_id":"76561198000000000","steam_name":"Beispiel"}
```

## Tests und Releaseprüfung

```sh
python -m unittest discover -s tests -v
python -m compileall -q app.py alias_ai.py gsi_engine.py steam_links.py tests
node --check static/admin.js
node --check static/name_search.js
node --check static/overlay.js
node --check static/draw_overlay.js
node tests/test_admin_search.cjs
```

Tests verwenden temporäre Datenbanken, synthetische GSI-Pakete und simulierte Modellobjekte. Sie decken Matchgrenzen, Teamwechsel, verzögerte Zuordnung, Serienreset, Multi-Account-Migration, Vorschläge, Auslosung/Rückholung, Zwölf-Stunden-Auswahl und Such-/Auswahlverhalten ab. Die JavaScript-Tests ersetzen Browserobjekte; sie sind keine visuelle Browserprüfung.

CI installiert nur `requirements-test.txt`. Kein Torch-/Modelldownload ist nötig. Linux wird mit Python 3.10, 3.11 und 3.12 getestet, Windows mit 3.11. Das prüft Python-Code, aber keine interaktive Ausführung der Batchstarter. Lokale Prüfungen und noch offene reale Integrationstests stehen im [Prüfbericht](../PRUEFBERICHT.md).

Vor einer Veröffentlichung zusätzlich auf Windows den Erststart und Modellcache prüfen, ein echtes CS2-Match mit Halbzeit/Wingman beobachten, Vorschläge bestätigen/ablehnen und OBS-Transparenz, Sound und Replay ansehen. Einen schemaverändernden Release gegen eine Kopie einer alten Datenbank testen und die Migration erneut ausführen.

## GitHub vorbereiten und pflegen

Das Paket enthält keine `.git`-Historie. Aus dem entpackten Projektordner beispielsweise:

```sh
git init
git add .
git status --short
git diff --cached --stat
git commit -m "Prepare PlayQueue source and documentation"
git branch -M main
```

Vor dem Commit die vorgemerkten Dateien prüfen. Danach ein eigenes leeres GitHub-Repository anlegen und dessen tatsächliche URL als Remote verwenden:

```sh
git remote add origin <DEINE_REPOSITORY_URL>
git push -u origin main
```

`<DEINE_REPOSITORY_URL>` durch die echte URL ersetzen. Kein Remote oder GitHub-Upload ist Bestandteil des Quellcodepakets.

`.gitignore` schließt persönliche Datenbanken, Sicherungen, `.venv`, Modelle, Geheimnisse und generierte Ausgaben aus. Sie entfernt keine bereits verfolgten Dateien: bei bestehenden Repositories beispielsweise `git rm --cached queue.db` verwenden und vor öffentlichem Push die bisherige Historie auf persönliche Daten/Geheimnisse prüfen. `.gitattributes` setzt reproduzierbare Zeilenenden, insbesondere CRLF für Windows-Batchdateien. `.editorconfig` beschreibt die Formatierung ohne bestehenden Code umzuschreiben.

Neue Dokumentation und Quellcode gemeinsam pflegen. Änderungen per Pull Request erläutern, relevante Tests ausführen und reale Integrationstests ehrlich von simulierten Tests trennen. Vor öffentlicher Veröffentlichung die Projektlizenz durch den Eigentümer festlegen; im Paket wurde keine Open-Source-Lizenz vergeben.
