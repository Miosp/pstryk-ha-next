# Integracja Pstryk Energy Home Assistant

Niestandardowa integracja do [Pstryka](https://pstryk.pl) — dynamicznej taryfy energii elektrycznej. Integracja używa oficjalnego API Pstryka i wystawia w Home Assistant godzinowe ceny rynkowe, bieżący koszt energii, zużycie z licznika oraz dane gotowe do podłączenia w panelu Energy Dashboard.

Projekt społecznościowy, niepowiązany z Pstrykiem ani przez niego wspierany.

## Funkcje

- **Ceny godzinowe na żywo**: aktualna cena, cena na następną godzinę i dokładny czas kolejnej zmiany ceny. Pełna krzywa cenowa na dany dzień jest wystawiona w atrybutach, więc nadaje się do wykresów.
- **Wyszukiwarka najtańszego okna**: analizuje ruchome okno o długości od 1 do 8 godzin w ramach dzisiejszych cen i wskazuje najtańszy przedział.
- **Czujnik binarny „czy tanio"**: jedna encja, która włącza się, gdy bieżąca godzina jest uznawana za tanią.
- **Rzeczywiste śledzenie kosztów**: koszt dzisiejszy / wczorajszy / od początku miesiąca w PLN, obliczany na podstawie danych z licznika, z podziałem na składniki (energia, dystrybucja, opłata handlowa, akcyza, VAT).
- **Czujniki zużycia**: kWh dzisiaj / wczoraj / w tym miesiącu oraz szacowana moc w kW z odczytów licznika o rozdzielczości minutowej. Czujniki mają ustawioną klasę urządzenia `energy`, więc można je bezpośrednio dodać do HA Energy Dashboard.
- **Ceny na jutro**: pobierane automatycznie, gdy Pstryk je opublikuje (zazwyczaj ok. 13:00–14:00).
- **Odporny klient API**: uwzględnia limity zapytań, ponawia nieudane próby i wywołuje ponowne uwierzytelnienie, jeśli klucz API przestanie działać.

## Wymagania

- Home Assistant **2025.6 lub nowszy** (integracja wymaga HA >= 2025.6; testowana na 2026.9).
- Konto Pstryk z taryfą dynamiczną i licznikiem zdalnym raportującym do Pstryka.
- **Klucz API Pstryk** — wygeneruj go dla swojego konta Pstryk zgodnie z oficjalną dokumentacją Pstryka.

## Instalacja

### HACS (zalecane)

1. W Home Assistant otwórz **HACS → ⋮ (trzy kropki) → Niestandardowe repozytoria**.
2. Dodaj `https://github.com/Miosp/pstryk-ha-next` w kategorii **Integracja**.
3. Znajdź **Pstryk Energy** w HACS i pobierz.
4. Zrestartuj Home Assistant.

### Ręcznie

Skopiuj `custom_components/pstryk_energy/` do katalogu `custom_components/` w konfiguracji HA, a potem zrestartuj Home Assistant.

> Jeśli wcześniej używałeś starej integracji `ha_Pstryk` albo innego komponentu `pstryk`, usuń je najpierw, aby uniknąć konfliktów domen i encji.

## Konfiguracja

1. Wejdź w **Ustawienia → Urządzenia i usługi → Dodaj integrację** i wyszukaj **Pstryk Energy**.
2. Wklej klucz API (z aplikacji Pstryk → **Integracje**). Klucz jest sprawdzany na żywo podczas konfiguracji: błędny klucz wywali się od razu, a nie dopiero w trakcie działania.
3. Zatwierdź. Encje pojawią się po pierwszym odświeżeniu koordynatora (w ciągu minuty lub dwóch).

Żeby później zmienić klucz API, usuń integrację i dodaj ją ponownie. Wszystkie pozostałe ustawienia znajdują się w sekcji Konfiguruj (opcje).

## Encje

| Encja | Opis | Warte uwagi atrybuty |
|---|---|---|
| `sensor.pstryk_current_price` | Cena bieżącej godziny w PLN/kWh (wg wybranej podstawy) | `today_prices`, `tomorrow_prices`, `hour_rank_today`, `tge_spot`, `dist`, `service`, `vat`, `excise`, `is_cheap`, `is_expensive` |
| `sensor.pstryk_next_hour_price` | Cena kolejnej godziny | `delta_vs_current` |
| `sensor.pstryk_next_price_change` | Moment następnej zmiany ceny | `new_price`, `delta` |
| `sensor.pstryk_today_avg_price` | Średnia cena dzisiaj | `min`, `max`, `min_hour`, `max_hour` |
| `sensor.pstryk_tomorrow_avg_price` | Średnia cena jutro (niedostępna do czasu publikacji) | `min`, `max`, `min_hour`, `max_hour` |
| `sensor.pstryk_cheapest_window` | Średnia cena najtańszego N-godzinnego okna dzisiaj | `start`, `end`, `length` |
| `binary_sensor.pstryk_is_cheap_now` | ON, gdy bieżąca godzina jest tania | — |
| `sensor.pstryk_cost_today` | Koszt energii od początku dnia (PLN) | rozbicie na składniki (`energy_net`, `dist_var_net`, `dist_fix_net`, `service_net`, `excise`, `vat`) |
| `sensor.pstryk_cost_yesterday` | Całkowity koszt wczoraj (PLN) | rozbicie na składniki |
| `sensor.pstryk_cost_month` | Koszt od początku miesiąca (PLN) | `forecast`, `avg_per_day`, `daily` |
| `sensor.pstryk_hourly_cost` | Koszt ostatniej zakończonej godziny (PLN) | `as_of` |
| `sensor.pstryk_consumption_today` | Zużycie kWh dzisiaj | `hourly` (kWh + koszt per godzina) |
| `sensor.pstryk_consumption_yesterday` | Zużycie kWh wczoraj | — |
| `sensor.pstryk_consumption_month` | Zużycie kWh w tym miesiącu (dni zakończone) | — |
| `sensor.pstryk_power` | Szacunkowa moc chwilowa (kW) | — |

Encja `sensor.pstryk_consumption_today` ma klasę urządzenia `energy` i klasę stanu `total_increasing`, więc można ją dodać bezpośrednio do HA Energy Dashboard jako źródło zużycia z sieci.

## Opcje

Otwórz okno **Konfiguruj** przy integracji:

| Opcja | Zakres | Domyślnie | Znaczenie |
|---|---|---|---|
| Długość najtańszego okna | 1–8 godzin | 3 | Rozmiar okna używanego przez `sensor.pstryk_cheapest_window` |
| Podstawa ceny | brutto / netto | brutto | Czy czujniki podają ceny z VAT (`brutto`) czy bez (`netto`) |
| Interwał odpytywania zużycia | 5–30 minut | 10 | Jak często odświeżane są dane licznika i zużycia |

## Pulpity

Katalog [`dashboards/`](dashboards/) zawiera trzy gotowe karty [ApexCharts](https://github.com/RomRider/apexcharts-card) oraz przewodnik po panelu Energy Dashboard:

- `price-today-tomorrow.yaml`: godzinowy wykres cen na dziś i na jutro. Łatwo na nim wypatrzeć godziny tanie i drogie.
- `price-vs-consumption.yaml`: cena nałożona na Twoje godzinowe zużycie.
- `cost-month.yaml`: słupki dziennych kosztów dla bieżącego miesiąca z linią prognozy.

Jak używać:

1. Zainstaluj wtyczkę interfejsu apexcharts-card przez HACS (kategoria Dashboard).
2. Otwórz panel → Edytuj panel → Dodaj kartę Ręcznie (lub dodaj do stosu pionowego) i wklej kod YAML z pliku.
3. Jeśli w Twojej instalacji zmieniono nazwy encji, dostosuj linie `entity:`.

### Panel Energy Dashboard

`sensor.pstryk_consumption_today` podłącza się do natywnego panelu HA Energy Dashboard. Instrukcja krok po kroku znajduje się w [`dashboards/energy-dashboard.md`](dashboards/energy-dashboard.md): dodaj ją w sekcji **Energia → Zużycie z sieci**, a opcjonalnie użyj `sensor.pstryk_cost_today`, żeby porównać oficjalne szacunki kosztów ze składnikami rozliczeniowymi Pstryka.

## Rozwiązywanie problemów

- **Ceny na jutro są `unavailable` / ich brak.** Normalne do mniej więcej 13:00–14:00. Dopiero wtedy Pstryk publikuje ceny na kolejny dzień.
- **`sensor.pstryk_power` pokazuje 0 albo nic zaraz po instalacji.** Potrzebuje świeżego odczytu minutowego z API; poczekaj jeden interwał odpytywania.
- **Limity zapytań / nieudane aktualizacje.** API nakłada limity częstotliwości zapytań. Po osiągnięciu limitu klient wstrzymuje ponowne próby i czeka na kolejny zaplanowany interwał. Zmniejszaj częstotliwość odpytywania tylko wtedy, gdy błędy nadal występują.
- **Błędy `404` / nieprawidłowy klucz albo monit o ponowną autoryzację.** Klucz API został odrzucony. Wygeneruj go ponownie w aplikacji Pstryk (Integracje) i skonfiguruj integrację od nowa.
- **Brak encji po instalacji.** Sprawdź, czy integracja się załadowała (Ustawienia → Urządzenia i usługi → Pstryk Energy), oraz czy usunąłeś starszy niestandardowy komponent Pstryka.
- **Diagnostyka.** Ustawienia → Urządzenia i usługi → Pstryk Energy → *urządzenie* → ⋮ → **Pobierz diagnostykę**. Eksport jest zanonimizowany: przed zapisem znika z niego klucz API i dane osobowe.

## Rozwój

To repozytorium używa [uv](https://docs.astral.sh/uv/) do zarządzania środowiskiem i zależnościami:

```bash
uv sync       # tworzy .venv z zależnościami deweloperskimi
uv run pytest # uruchamia testy (offline, ~1s)
```

Testy działają w pełni offline na nagranych fixture'ach API w
`tests/fixtures/` (dane osobowe licznika podmienione na wartości
syntetyczne; ceny to publiczne dane giełdowe TGE). Żeby nagrać fixture'y
na żywo, umieść klucz w pliku `.env` (`PSTRYK_API_KEY=...`) i uruchom:

```bash
uv run python scripts/record_fixtures.py
```

Skrypt czyta klucz z `.env` (gitignored) i nigdy nie wypisuje go ani nie zapisuje do fixture'ów.

Zanim zmienisz cokolwiek związanego z czasem lub strefą czasową, przeczytaj
`docs/architecture.md` (projekt, zweryfikowany kontrakt API, zasady DST)
oraz `docs/development.md` (wzorce testów, dziwactwa harnessu, proces
wydawniczy).

## Podziękowania i źródła

Przy powstawaniu projektu korzystaliśmy z poniższych repozytoriów i materiałów:

- [balgerion/ha_Pstryk](https://github.com/balgerion/ha_Pstryk): pierwotna
  integracja community dla Pstryka, której używaliśmy przed napisaniem tej
  od zera. Jej ograniczenia (wymóg MQTT, hardcodowana strefa czasowa, brak
  czujników zgodnych z panelem Energy Dashboard) zdecydowały, co tutaj
  poprawiliśmy.
- [balgerion/ha_Pstryk_card](https://github.com/balgerion/ha_Pstryk_card):
  autorska karta Lovelace. Zastąpiliśmy ją gotowymi konfiguracjami
  ApexCharts w [`dashboards/`](dashboards/).
- [Dokumentacja API Pstryk](https://api.pstryk.pl/integrations/swagger/):
  oficjalna specyfikacja OpenAPI endpointu integracji. Faktyczne zachowanie
  API (semantyka koszyków `temporal=latest`, moment publikacji cen
  jutrzejszych) sprawdziliśmy dodatkowo żywymi zapytaniami.
- [RomRider/apexcharts-card](https://github.com/RomRider/apexcharts-card):
  wtyczka frontendowa, na której działają wszystkie wykresy w `dashboards/`.
- [hacs](https://hacs.xyz): mechanizm dystrybucji integracji.
- [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component):
  harness testowy, dzięki któremu integrację da się testować offline.

## Licencja

Projekt udostępniono na licencji [MIT](LICENSE).
