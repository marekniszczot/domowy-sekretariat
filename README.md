# Domowy Sekretariat

Aplikacja, która ze zdjęcia pisma urzędowego robi werdykt według domowego regulaminu. Działa na GCP, a dane zostają w UE.

Pełny opis projektu powstaje. Infrastruktura jest opisana w [`infra/README.md`](infra/README.md).

## Konfiguracja domu

Imiona, formy imion, role i adresy e-mail domowników nigdy nie trafiają do repozytorium. Format opisuje [`household.example.yaml`](household.example.yaml).

```sh
cp household.example.yaml household.yaml           # plik jest w .gitignore
uv run pre-commit install                          # hook blokuje dane domu w commitach
GCLOUD_CONFIGURATION=<config> scripts/upload_household.sh <project-id>
```

Lokalnie aplikacja czyta `HOUSEHOLD_FILE=household.yaml`, a na Cloud Run sekret `HOUSEHOLD_SECRET=projects/<project-id>/secrets/household-config`. Hook pre-commit blokuje plik `household.yaml`, każdą formę imienia i e-mail z niego oraz ciągi z lokalnego pliku `.forbidden-strings` (np. nazwisko, ulica, domena).

## Sondy dostępności

Skrypt [`scripts/probes.py`](scripts/probes.py) sprawdza, które modele Gemini odpowiadają w których lokalizacjach Vertex AI, oraz czy Sensitive Data Protection (DLP) wykrywa polskie dane osobowe w syntetycznym piśmie.

```sh
GCLOUD_CONFIGURATION=<config> python3 scripts/probes.py <project-id> [--model <id> ...]
```

### Wyniki z 2026-10-10

**Gemini (Vertex AI)**

| model | europe-central2 | europe-west4 | global |
|---|---|---|---|
| `gemini-2.5-flash` | OK | OK | OK |
| `gemini-2.5-flash-lite` | OK | OK | OK |
| `gemini-2.5-pro` | OK | OK | OK |
| `gemini-3-flash-preview` | 404 | 404 | OK |

Modele `gemini-2.0-flash`, `gemini-3-pro-preview` i `gemini-3.0-flash` zwróciły 404 we wszystkich trzech lokalizacjach.

**Wniosek:** pipeline wywołuje Gemini 2.5 w `europe-central2` (Warszawa), czyli w tym samym regionie co pozostałe usługi. Gemini 3 Flash jest dostępny tylko przez endpoint `global`, który nie gwarantuje przetwarzania w UE. Dlatego nadaje się wyłącznie do eksperymentów na danych syntetycznych.

**DLP (`europe-central2`, `languageCode=pl`)**

Polskie infoTypes: `POLAND_PESEL_NUMBER`, `POLAND_NATIONAL_ID_NUMBER`, `POLAND_PASSPORT`.

| infoType | wykryty w syntetycznym piśmie |
|---|---|
| `POLAND_PESEL_NUMBER` | tak (VERY_LIKELY) |
| `IBAN_CODE` | tak (VERY_LIKELY) |
| `PHONE_NUMBER` | tak (VERY_LIKELY) |
| `STREET_ADDRESS` | tak (LIKELY), bez prefiksu „ul.” |
| `PERSON_NAME` | tak (LIKELY), razem ze zwrotem „Pan” |

Próbka to jedno krótkie pismo, więc wynik potwierdza dostępność usług, a nie jakość wykrywania. Skuteczność maskowania, zwłaszcza odmienionych imion, mierzy dopiero zbiór ewaluacyjny.
