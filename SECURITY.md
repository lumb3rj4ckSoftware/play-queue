# Sicherheit und Betrieb

## Aktueller Umfang

PlayQueue bindet standardmäßig ausschließlich an `127.0.0.1:5050`. Es ist eine lokale Desktop-/Streaming-Hilfe, kein abgesicherter öffentlicher Webdienst.

Der aktuelle Code hat keine Admin-Anmeldung, keine CSRF-Abwehr und keine Prüfung des GSI-Tokens aus `gamestate_integration_playqueue.cfg`. Der mitgelieferte Tokenwert ist ein Beispielwert und kein Zugangsschutz. Einige GET-Endpunkte verändern Queue oder Overlay; auch `/api/state` kann Hintergrund-Ergebnisse und Zähler übernehmen.

Den Server nicht über Portweiterleitung, öffentlichen Tunnel oder eine geänderte Bind-Adresse veröffentlichen. Ein Netzbetrieb benötigt zunächst Authentifizierung, GSI-Tokenvalidierung und eine Überarbeitung zustandsändernder Browseraktionen. Andere lokale Programme können auf die API zugreifen.

## Daten und Modelle

`queue.db` enthält Twitch-Namen, SteamIDs, Spielteilnahmen und Zuordnungen. Datenbankkopien und Logs ebenfalls vertraulich behandeln. Sie gehören nicht ins öffentliche Repository. `.gitignore` schützt neue ungetrackte Dateien, entfernt aber keine bereits committen Inhalte aus der Historie.

Die KI verarbeitet Namen lokal. Downloads und mögliche Metadatenprüfungen erfolgen über die Modellbibliothek; ein vollständiger expliziter `PLAYQUEUE_MODEL_PATH` ermöglicht lokales Laden. Nur Modelle aus vertrauenswürdiger Quelle einsetzen. Der aktuelle Loader verwendet `trust_remote_code=False` und Safetensors.

## Sicherheitsprobleme melden

Für sensible Details die private Sicherheitsmeldung des eigenen GitHub-Repositories verwenden, wenn dessen Eigentümer sie aktiviert hat. Andernfalls zuerst den Maintainer über einen vorhandenen privaten Kontaktkanal erreichen. Keine Geheimnisse oder persönliche Daten in öffentlichen Issues veröffentlichen. Dieses Paket enthält keine erfundene Kontaktadresse und keine Garantie eines bestimmten Reaktionszeitraums.
