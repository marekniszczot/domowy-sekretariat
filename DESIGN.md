---
# gstack: design-md-format=spec
name: Domowy Sekretariat
description: Domowa pieczątka. Pismo jest szare i ciche, a decyzja domu ląduje na nim jak pieczątka; spokój z jasności, nie z miękkości.
colors:
  ground: "#F4F5F7"
  sheet: "#FFFFFF"
  ink: "#1D2A5C"
  on-ink: "#FFFFFF"
  text-muted: "#5B6478"
  rule: "#DDE0E6"
  veil: "rgba(29, 42, 92, 0.08)"
  highlight: "#FFE58A"
  state-none: "#1E6B3A"
  on-state-none: "#FFFFFF"
  state-todo: "#F2B33D"
  on-state-todo: "#2A1A00"
  state-todo-text: "#8A4B00"
  state-unsure: "#4A5A72"
  on-state-unsure: "#FFFFFF"
  state-urgent: "#B3261E"
  on-state-urgent: "#FFFFFF"
  dark-ground: "#12151C"
  dark-sheet: "#1B1F29"
  dark-ink: "#E8EAF0"
  dark-on-ink: "#12151C"
  dark-text-muted: "#9AA3B5"
  dark-rule: "#2C3240"
  dark-veil: "rgba(232, 234, 240, 0.06)"
  dark-highlight: "#5A4A12"
  dark-state-none: "#6FD49A"
  dark-state-todo: "#F5C15A"
  dark-state-unsure: "#A9B8CF"
  dark-state-urgent: "#FF8A80"
  dark-on-state: "#12151C"
typography:
  display:
    fontFamily: Bricolage Grotesque
    fontWeight: 800
    fontSize: 1.75rem
    lineHeight: 1.1
    fontVariationSettings: '"opsz" 96'
  display-group:
    fontFamily: Bricolage Grotesque
    fontWeight: 800
    fontSize: 1.3rem
    fontVariationSettings: '"opsz" 48'
  title:
    fontFamily: Bricolage Grotesque
    fontWeight: 800
    fontSize: 2rem
    lineHeight: 1.1
  body:
    fontFamily: Atkinson Hyperlegible Next
    fontWeight: 400
    fontSize: 1.0625rem
    lineHeight: 1.5
  body-strong:
    fontFamily: Atkinson Hyperlegible Next
    fontWeight: 700
    fontSize: 1.0625rem
  label:
    fontFamily: Atkinson Hyperlegible Next
    fontWeight: 600
    fontSize: 0.875rem
    letterSpacing: 0
  mono:
    fontFamily: Atkinson Hyperlegible Mono
    fontWeight: 600
    fontSize: 1.0625rem
    fontFeature: tnum
  mono-verdict:
    fontFamily: Atkinson Hyperlegible Mono
    fontWeight: 600
    fontSize: 1.175rem
    fontFeature: tnum
rounded:
  stamp: 4px
  sm: 6px
  md: 10px
  lg: 16px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
  touch-min: 48px
  button-height: 56px
  row-height: 72px
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
    rounded: "{rounded.sm}"
    height: "{spacing.button-height}"
  button-secondary:
    backgroundColor: transparent
    textColor: "{colors.ink}"
    borderColor: "{colors.ink}"
    borderWidth: 2px
    rounded: "{rounded.sm}"
    height: "{spacing.button-height}"
  button-danger:
    backgroundColor: transparent
    textColor: "{colors.state-urgent}"
    borderColor: "{colors.state-urgent}"
    rounded: "{rounded.sm}"
  chip:
    borderColor: "{colors.ink}"
    rounded: "{rounded.full}"
    height: "{spacing.touch-min}"
  chip-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
  stamp:
    borderStyle: 6px double (fill colour mixed 55% with black; 55% with white in dark mode)
    rounded: "{rounded.stamp}"
    padding: 14px 16px 16px
  mini-stamp:
    size: 48px
    borderStyle: 4px double
    rounded: 3px
  deadline-unconfirmed:
    borderStyle: 2px dashed
    borderColor: "{colors.ink}"
    background: 135deg hatching, veil 4px / transparent 5px
    rounded: "{rounded.sm}"
  deadline-confirmed:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
    rounded: "{rounded.sm}"
  deadline-overdue:
    backgroundColor: "{colors.state-urgent}"
    textColor: "{colors.on-state-urgent}"
    rounded: "{rounded.sm}"
  input:
    borderColor: "{colors.text-muted}"
    borderWidth: 2px
    rounded: "{rounded.sm}"
    height: 52px
  sheet:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.lg} {rounded.lg} 0 0"
  undo-bar:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
    rounded: "{rounded.md}"
  tab-bar:
    backgroundColor: "{colors.sheet}"
    activeColor: "{colors.ink}"
    inactiveColor: "{colors.text-muted}"
---

# Domowy Sekretariat

## Overview

**Creative North Star:** Domowa pieczątka. Urzędowe pisma straszą pieczęciami i niebieskim tuszem; tutaj dom przejmuje oba. Pismo jest wyszarzone i ciche, a decyzja domu ląduje na nim jak pieczątka.
**Product context:** PWA na iPhone (Safari, dodana do ekranu początkowego) dla domowników jednego domu. Zdjęcie pisma (bank, urząd skarbowy, ubezpieczyciel, wspólnota, telekom, energia) zamienia się w werdykt z terminem i powodem z Domowego regulaminu. Projektujemy najpierw dla osoby, która dziś przekazuje pisma dalej, bo nie chce mierzyć się z urzędowym językiem.
**To ma zostać w głowie:** „Pismo przestało straszyć.” Każda decyzja wizualna ma temu służyć.
**Mode per surface:** Operate: listy, wgrywanie, arkusz „Przekaż”, edytor regulaminu. Read: karta werdyktu (krótkie wyjaśnienie i cytaty).
**Reference sites:** brak (research konkurencji pominięty świadomie).
**Key characteristics:**
- Pierwsze 3 sekundy: „ktoś już to ostemplował”. Jedna pieczątka, czasownik, termin.
- Kolor występuje wyłącznie jako stan pisma; reszta to tusz i szarości.
- Płasko: bez kart w kartach, wiersze oddziela odstęp.
- Duży, czytelny tekst (Atkinson Hyperlegible) skalowany z Dynamic Type.

## Colors

**Strategy:** Restrained. Tusz i chłodne szarości, a kolor jest zarezerwowany dla czterech stanów pisma. Dzięki temu „Pilne” zachowuje wagę: jest jedyną czerwoną rzeczą na ekranie.
**Light or dark:** jasny jako podstawowy, bo pisma czyta się przy stole albo w przedpokoju, w dzień lub przy lampie, z papierem w drugiej ręce. Ciemny tryb włącza się z ustawień iOS (`prefers-color-scheme`), tokeny `dark-*`.

- **Tusz** (`ink`) jest kolorem tekstu, głównego przycisku, potwierdzonego terminu i paska „Cofnij”. Granat zamiast czerni to świadome przejęcie urzędowego koloru.
- **Tło** (`ground`) to chłodna szarość, celowo nie krem. **Arkusz** (`sheet`) to biel dla arkuszy od dołu, pól i paska zakładek.
- **Cztery stany** (DR-4) zawsze idą razem z ikoną i słowem: ✓ `state-none` „Nic nie musisz robić”, ● `state-todo` „Do zrobienia do <data>”, ? `state-unsure` „Nie mam pewności, przekaż dalej”, ▲ `state-urgent` „Pilne”. Bursztyn jako tekst na tle używa `state-todo-text`, bo czysty bursztyn nie ma kontrastu.
- **Zakreślacz** (`highlight`) oznacza w cytatach fragment pisma, który uruchomił werdykt.
- **Kontrasty (jasny, względem `ground`):** tusz 12,5:1; tekst drugorzędny 5,4:1; zielony 6,0:1; bursztynowy tekst 6,2:1; szaroniebieski 6,4:1; czerwony 6,0:1. Tekst na wypełnieniach: biały na zielonym 6,5:1, na szaroniebieskim 7,0:1, na czerwonym 6,5:1; `on-state-todo` na bursztynie 9,1:1. Ciemny: tekst 15,2:1, stany ≥ 8:1.
- **Znane napięcie:** tusz i `state-unsure` różnią się tylko 1,95:1. Rozróżniają je ikona „?”, słowo i podwójna ramka pieczątki. Nigdy nie pokazuj stanu „?” bez ikony i słowa.
- W ciemnym trybie hierarchię trzyma `dark-sheet` nad `dark-ground`, a stany rozjaśniają się do pasteli z ciemnym tekstem. Bez poświat.

## Typography

Dwie rodziny, trzy role. Wszystkie z Google Fonts (OFL), z podzbiorem latin-ext (ą ć ę ł ń ó ś ź ż), sprawdzone 2026-10-09.

- **Display: Bricolage Grotesque 800.** Masywny, lekko nieregularny, jak litery wycięte w gumie pieczątki. Wyłącznie dwie role: czasownik werdyktu na pieczątce i nagłówki grup oraz tytuły ekranów. Nigdy w treści, przyciskach ani etykietach, bo inaczej interfejs zrobi się „zabawny”. Pomocniczo w wadze 600 dla zdania reguły w sekcji „Dlaczego <imię>”.
- **Body i UI: Atkinson Hyperlegible Next.** Zaprojektowany przez Braille Institute dla czytelności przy słabym wzroku. Treść, przyciski, etykiety.
- **Mono: Atkinson Hyperlegible Mono** z cyframi tabelarycznymi: odliczanie („za 6 dni”), daty i kwoty. Zawsze w pełnym rozmiarze tekstu, nigdy jako drobne, rozstrzelone etykiety.
- **Ładowanie:** `https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Mono:wght@400;600&family=Atkinson+Hyperlegible+Next:wght@400;600;700;800&family=Bricolage+Grotesque:opsz,wght@12..96,600..800&display=swap`. Docelowo samohostowane w obrazie PWA (offline, bez zapytań do Google przy każdym otwarciu).
- **Skala i Dynamic Type (DR-14):** `html { font: -apple-system-body; font-family: "Atkinson Hyperlegible Next", sans-serif; }`. `-apple-system-body` służy tylko do odczytu rozmiaru z ustawień iOS, nie jako krój. 1rem = systemowy rozmiar tekstu (17 px domyślnie), więc body 1.0625rem daje 18 px i rośnie razem z ustawieniem. Kolejne poziomy różnią się wyraźnie: 0.875 / 1.0625 / 1.3 / 1.75 / 2rem.
- **Daty słowami:** „za 6 dni · do czwartku, 15 października” zamiast samego „15.10.2026”. Skrót „15.10” tylko w wierszach listy.

## Layout

- **Mobile-first 390 px**, boczny margines 16 px, jedna kolumna. Treść leży płasko na `ground`.
- **Karta werdyktu (DR-1):** wyszarzona miniatura pisma (pasek 96 px, `filter: grayscale(1)` i `veil`), na którą od dołu nachodzi pieczątka (−28 px). Pod nią nadawca i data doręczenia, „Pewne”/„Sprawdź”, „O co chodzi”, „Jeśli zignorujesz”, „Dlaczego <imię>”, wiersz „Pokaż w piśmie”. Przyciski akcji przypięte do dołu z `env(safe-area-inset-bottom)`.
- **Listy (DR-3):** tytuł ekranu, nagłówki grup w Bricolage, wiersze 72 px: mini-pieczątka 48 px, typ nadawcy i właściciel, po prawej odliczanie w mono i słowo stanu. Odstęp zamiast linii.
- **Od 900 px (DR-15):** zakładki przechodzą w lewy pasek boczny (220 px), „Wszystkie” = lista (360 px) i pismo obok, treść pisma max 680 px. Bez osobnego układu tabletowego.
- **Rytm:** baza 8 px; 24 px między sekcjami karty, 28 px przed nagłówkiem grupy, 6 px między wierszami.

## Elevation & Depth

Prawie płasko. Głębię daje kolejność warstw, nie cienie:
- `sheet` nad `ground` dla arkuszy od dołu i paska zakładek; arkusz ma przyciemnione tło `rgba(18,21,28,.45)`.
- Jedyny cień w aplikacji pojawia się w animacji przybicia (pieczątka w powietrzu) i znika w chwili uderzenia.
- Żadnych poświat, gradientów ani szkła.

## Shapes

- Pieczątka: promień 4 px i podwójna ramka. To jedyny „ornament” systemu.
- Przyciski, pola i chipy daty: 6 px. Arkusz: 16 px u góry. Pasek „Cofnij”: 10 px.
- Pigułka (`full`) wyłącznie dla chipów wyboru („Dziś / Wczoraj / Wcześniej…”), żeby odróżniały się od akcji.
- Wewnętrzny promień = zewnętrzny minus odstęp.

## Components

- **Pieczątka werdyktu:** wypełnienie w kolorze stanu, podwójna ramka 6 px, linia stanu (ikona + słowo, 16 px, 700), czasownik w Bricolage, termin w mono. Stan zawsze z ikoną i słowem. Etykieta VoiceOver czyta całość: „Do zrobienia. Wypowiedz umowę albo nic nie rób. Za 6 dni, do czwartku 15 października.”
- **Mini-pieczątka (lista):** 48 px, podwójna ramka 4 px, ikona stanu. Termin niezatwierdzony: kreskowanie 30% i przerywana ramka („niedobita pieczątka”). Pismo prywatne: szara z kłódką, tylko metadane (DR-5).
- **Termin (DR-7):** niezatwierdzony = przerywana ramka w tuszu, kreskowanie, „najpóźniej 15.10” + „Sprawdź”; zatwierdzony = wypełniony tusz; po terminie = czerwony z ▲.
- **Przyciski:** główny w tuszu (56 px), drugorzędny z obrysem 2 px, tekstowy z podkreśleniem, niszczący z czerwonym obrysem (tylko „Usuń pismo”). Stany: `:focus-visible` = obrys 3 px w tuszu z odstępem 3 px; `:active` = przyciemnienie wypełnienia o 8%; `disabled` = krycie 45% i `aria-disabled`.
- **Arkusz „Przekaż” (DR-16):** podpowiedź z regulaminu jako jeden duży przycisk w tuszu (imię w Bricolage, powód słowami), potem „Albo komuś innemu:” jako przyciski drugorzędne, na dole „Anuluj”.
- **Pasek „Cofnij” (DR-8):** tusz, 56 px, 8 s, nad paskiem zakładek.
- **Komunikaty:** tło `veil`, ikona stanu i zdanie w 1. osobie albo w trybie rozkazującym (DR-18). Bez kolorowych krawędzi.
- **Pola:** etykieta nad polem, obrys 2 px `text-muted`, błąd = czerwony obrys i podpowiedź pogrubiona na czerwono.
- **Kroki przetwarzania (DR-6):** lista 56 px; zakończony krok = ✓ zielony i tekst drugorzędny, bieżący = spinner w tuszu i pogrubienie.

## Do's and Don'ts

- Do: zawsze pokazuj stan jako kolor + ikona + słowo.
- Do: trzymaj Bricolage wyłącznie w czasowniku werdyktu, nagłówkach grup i tytułach ekranów.
- Do: pisz daty słowami na karcie werdyktu i odliczanie w mono.
- Do: zachowaj cele dotykowe ≥ 48 px i tekst ≥ 18 px przy domyślnym rozmiarze.
- Do: formy neutralne rodzajowo (tryb rozkazujący, 1. osoba, strona bierna).
- Don't: nie dodawaj koloru poza czterema stanami (żadnych „brandowych” akcentów, gradientów, ikon w kolorowych kółkach).
- Don't: nie zamykaj treści w kartach i nie zagnieżdżaj kart; nie używaj kolorowej lewej krawędzi jako oznaczenia.
- Don't: nie obracaj pieczątki w stanie spoczynku; czytelność jest ważniejsza niż realizm.
- Don't: żadnych iskierek AI, robotów ani maskotek; sekretariat mówi zdaniami.
- Don't: nie pokazuj pewności jako liczby ani kodów NONE/SELF/FORWARD.

## Motion

- **Approach:** minimal-functional plus jeden autorski moment.
- **Easing:** enter(ease-out) exit(ease-in) move(ease-in-out).
- **Duration:** micro(50-100ms) short(150-250ms) medium(250-400ms) long(400-700ms).
- **The one authored moment: przybicie pieczątki.** `stamp-drop` 420 ms: pieczątka spada z góry (`translateY(-48px) scale(1.45) rotate(-4deg)`, cień uniesienia, ease-in jak grawitacja), w 55% uderza (`scale(.965)`, cień znika), potem osiada (1.012 → 1). Równolegle `ink-dry` 900 ms: w chwili kontaktu tusz jest mokry (`saturate(1.5) brightness(.78)`) i schnie do koloru tokenu. W chwili uderzenia kartka drga (`jolt`, 3 px w dół i z powrotem, 180 ms, opóźnienie 230 ms).
- **Kiedy:** tylko przy pierwszym obejrzeniu nowego werdyktu (po przetworzeniu albo z kropką „nowe”). Ponowne otwarcie pisma pokazuje pieczątkę bez animacji.
- **Ograniczony ruch:** przy `prefers-reduced-motion: reduce` pieczątka tylko się pojawia (opacity 150 ms), bez spadku i drgania.
- **Pozostałe:** kroki przetwarzania odhaczają się po kolei; arkusz wjeżdża od dołu (250 ms, ease-out); pasek „Cofnij” pojawia się i znika przez opacity.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-10-09 | Initial design system created („Domowa pieczątka”) | /design-consultation (DT1, DR-13). Kierunek ma realizować „Pismo przestało straszyć”; research konkurencji pominięty, synteza własnego szkicu i niezależnego subagenta Claude („Pieczątka”). Podgląd HTML zatwierdzony. |
| 2026-10-09 | Display: Bricolage Grotesque tylko w dwóch rolach | Charakter gumowej pieczątki dla werdyktu; poza tymi rolami Atkinson dla czytelności. |
| 2026-10-09 | Animacja: uderzenie z mokrym tuszem, tylko przy pierwszym obejrzeniu | Wybrana z trzech wariantów jako najbardziej „pieczątkowa”; ograniczenie do pierwszego obejrzenia, żeby się nie nudziła. |
| 2026-10-09 | Odrzucone: kolorowa lewa krawędź przy „Jeśli zignorujesz”, krem z szeryfem („Spokojny papier” jako gotowiec) | Wzorce AI-slop / przewidywalny kierunek; „Jeśli zignorujesz” oznaczone ikoną ▲ i nagłówkiem. |
