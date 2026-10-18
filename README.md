# Domowy Sekretariat

Aplikacja na telefon, która ze zdjęcia pisma robi decyzję według domowego regulaminu: czy trzeba coś zrobić, kto ma się tym zająć i do kiedy. Pismo z banku, urzędu, od ubezpieczyciela czy dostawcy prądu trafia do właściwego domownika, a termin nie ucieka, bo aplikacja przypomina o nim mailem. Działa na Google Cloud, dane zostają w UE, a model językowy nie widzi danych osobowych.

<p>
  <img src="docs/img/karta-do-zrobienia.png" width="195" alt="Karta „Do zrobienia”: Opłacić zaległą fakturę, za 11 dni">
  <img src="docs/img/karta-pilne.png" width="195" alt="Karta „Pilne”: Przekaż: Jan">
  <img src="docs/img/karta-manipulacja.png" width="195" alt="Karta „Nie mam pewności”: pismo zawiera polecenia dla programu">
  <img src="docs/img/moje-pisma.png" width="195" alt="Lista „Moje pisma” z terminami">
</p>

<sub>Prawdziwe odpowiedzi aplikacji na fikcyjne pisma z zestawu testowego.</sub>

## Jak to działa

Domownicy spisują regulamin zwykłym językiem, np. „Zaległości i wezwania do zapłaty od dostawców prądu, gazu i internetu. Zajmuje się tym Jan.”. Po zrobieniu zdjęcia pisma aplikacja pokazuje kartę w jednym z czterech stanów: **Nic nie musisz robić**, **Do zrobienia**, **Nie mam pewności** albo **Pilne**. Karta podaje czynność, termin, regułę, która zadziałała, i cytat z pisma. Regulamin tylko podpowiada, komu przekazać pismo. Przekazuje człowiek, jednym kliknięciem.

```mermaid
flowchart LR
    A[Zdjęcie pisma] --> B[Document AI<br>odczyt tekstu]
    B --> C[Maskowanie<br>DLP + kod]
    C --> D[Gemini 2.5 Flash<br>+ regulamin]
    D --> E[Strażnik<br>w kodzie]
    E --> F[Terminy<br>i właściciel]
    F --> G[Karta i przypomnienia]
```

**Model proponuje, kod decyduje.** Gemini dostaje zamaskowane pismo i regulamin, a odpowiada w stałym formacie JSON: werdykt, numer reguły, cytaty, termin i pewność. Strażnik ([`sekretariat/guard.py`](sekretariat/guard.py)) kieruje pismo do człowieka, gdy:

- cytat nie występuje w piśmie albo reguły nie ma w regulaminie,
- pismo wydaje polecenia programowi („Ignore all previous instructions…”), co kod wykrywa niezależnie od promptu,
- pismo zawiera słowa z listy eskalacji, np. komornik, sąd, wypowiedzenie (edytowalna w aplikacji),
- model nie jest pewny albo nie odpowiedział.

Kod nigdy nie zamienia werdyktu na „nic nie rób”. Termin liczy kod, zawsze tak, żeby nie wypadł później niż prawdziwy, a zatwierdza go człowiek.

## Prywatność

- **Model nie widzi danych osobowych.** Imiona i nazwiska domowników są zamieniane na `OSOBA_1`, `OSOBA_2`, inne osoby na `INNA_n`, a PESEL, numery kont, telefony i adresy na znaczniki w nawiasach ([`sekretariat/mask.py`](sekretariat/mask.py)). Regulamin też trafia do modelu tylko ze znacznikami. Imiona wracają dopiero na ekranie zalogowanego domownika, w odpowiednim przypadku ([`sekretariat/inflect.py`](sekretariat/inflect.py)).
- **Wszystko w regionie UE:** usługi w `europe-central2` (Warszawa), odczyt tekstu w regionie `eu` Document AI.
- **Zdjęcia pism** są automatycznie usuwane z Cloud Storage po 30 dniach. Odczytany tekst, werdykty i terminy zostają w Firestore. Automatyczne usuwanie tekstu i przycisk „Usuń pismo” są w planach.
- **Logi** zawierają identyfikatory pism i statusy, nigdy treść.
- **Repozytorium** zawiera tylko fikcyjne pisma i fikcyjny dom. Dane prawdziwego domu leżą w Secret Manager, a hook pre-commit blokuje je w commitach.

## Ewaluacja

`python -m sekretariat.eval` puszcza 53 fikcyjne pisma z [`eval/cases/`](eval/cases/) przez prawdziwe maskowanie, model, strażnika i liczenie terminów, każde pismo 3 razy, z fikcyjnym domem i regulaminem testowym z [`eval/`](eval/). Wśród pism są próby manipulacji, terminy względne („14 dni od doręczenia”) i pouczenia, które terminem nie są.

- **Bramka twarda:** zero fałszywych „nic nie rób”, każda próba manipulacji przekazana człowiekowi, żaden adres domowy w tekście dla modelu.
- **Bramka miękka:** trafność werdyktu, reguły i terminu najwyżej 3 pp poniżej [`eval/baseline.json`](eval/baseline.json), który zmienia się tylko jawnym commitem (`--write-baseline`).
- **Raportowane bez bramki:** adresat, typ nadawcy, tekst na karcie (imiona w przypadku, którego kod nie rozpozna, i za długa czynność na pieczątce).

Workflow `eval` robi to na każdym PR z tego repozytorium i wkleja raport jako komentarz. Vertex AI zwraca czasem pojedyncze błędy usługi, które liczą się jako chybienia, więc przed wnioskami warto powtórzyć przebieg.

```sh
GCLOUD_CONFIGURATION=<config> GCP_PROJECT=<project-id> uv run python -m sekretariat.eval [--only <id> ...]
```

Nowe przypadki dopisuje się do plików YAML z oczekiwanym werdyktem, regułą, terminem, adresatem i typem nadawcy. W zbiorze są tylko wymyślone pisma, osoby i firmy.

## Architektura

| Warstwa | Co |
| --- | --- |
| Aplikacja | Python 3.13, FastAPI, szablony Jinja2 z htmx, PWA na iPhone'a |
| Uruchamianie | Cloud Run: usługa `web` i job `jobs` (przypomnienia, Cloud Scheduler o 7:00), Cloud Tasks z ponowieniami |
| AI i dane | Document AI, Sensitive Data Protection, Vertex AI (Gemini 2.5 Flash), Firestore, Cloud Storage, Secret Manager |
| Logowanie i poczta | konto Google, przypomnienia przez SMTP z własnej domeny |
| Infrastruktura | Terraform ([`infra/`](infra/)), GitHub Actions z Workload Identity Federation, bez kluczy kont serwisowych |

Najważniejsze moduły: [`pipeline.py`](sekretariat/pipeline.py) (etapy przetwarzania pisma), [`llm.py`](sekretariat/llm.py) (prompt i schemat odpowiedzi), [`guard.py`](sekretariat/guard.py), [`mask.py`](sekretariat/mask.py), [`deadlines.py`](sekretariat/deadlines.py), [`web/`](sekretariat/web/) (ekrany). Wygląd opisuje [`DESIGN.md`](DESIGN.md).

## Uruchomienie u siebie

Aplikacja korzysta z usług Google Cloud, więc potrzebny jest własny projekt GCP z płatnościami. Przy kilkudziesięciu pismach miesięcznie koszt to kilka złotych.

1. **Infrastruktura:** projekt, Terraform, klient OAuth i poczta według [`infra/README.md`](infra/README.md).
2. **Dom:** skopiuj przykład i wpisz domowników, ich formy imion i adresy.

   ```sh
   cp household.example.yaml household.yaml           # plik jest w .gitignore
   uv run pre-commit install                          # hook blokuje dane domu w commitach
   GCLOUD_CONFIGURATION=<config> scripts/upload_household.sh <project-id>
   ```

   Format opisuje [`household.example.yaml`](household.example.yaml). Hook pre-commit blokuje plik `household.yaml`, każdą formę imienia i e-mail z niego oraz ciągi z lokalnego pliku `.forbidden-strings` (np. nazwisko, ulica, domena).
3. **Wdrożenie:** `GCLOUD_CONFIGURATION=<config> scripts/deploy.sh <project-id>` buduje obraz i wdraża go do `web` i `jobs`.

Testy działają bez chmury:

```sh
uv sync
uv run pytest                      # testy jednostkowe
uv run pytest -m e2e               # ekrany w WebKit jako iPhone (raz: uv run playwright install webkit)
uv run pytest -m integration       # prawdziwe DLP i Gemini, potrzebne GCLOUD_CONFIGURATION i GCP_PROJECT
```

## Sondy dostępności

Skrypt [`scripts/probes.py`](scripts/probes.py) sprawdza, które modele Gemini odpowiadają w których lokalizacjach Vertex AI, oraz czy Sensitive Data Protection wykrywa polskie dane osobowe w syntetycznym piśmie.

```sh
GCLOUD_CONFIGURATION=<config> python3 scripts/probes.py <project-id> [--model <id> ...]
```

W październiku 2026 Gemini 2.5 Flash, Flash-Lite i Pro odpowiadały w `europe-central2`, a Gemini 3 Flash tylko przez endpoint `global`, który nie gwarantuje przetwarzania w UE. Dlatego aplikacja wywołuje Gemini 2.5 w Warszawie, w tym samym regionie co pozostałe usługi. DLP wykrył w próbce PESEL, IBAN, telefon, adres i imię z nazwiskiem. Zbiór ewaluacyjny pokazał jednak, że adresu z numerem mieszkania („ul. Lipowa 7 m. 3”) ani ulicy w środku zdania nie łapie, więc [`mask.py`](sekretariat/mask.py) ma własne reguły dla adresów.

## O projekcie

Projekt zaliczeniowy kursu Me+AI w CampusAI. Powstał we współpracy z Claude Code. W planach: porównanie, ile trafności kosztuje maskowanie danych (bez maskowania, z maskowaniem i na modelu lokalnym), oraz agent z pamięcią spraw, który łączy pisma w wątki i za zgodą człowieka szkicuje odpowiedzi i wpisuje terminy do kalendarza.
