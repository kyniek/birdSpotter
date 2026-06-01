# Plan Implementacji — BirdTracker Server

> Serwer API do śledzenia stad ptaków — Python 3.11+, FastAPI, Neo4j, SMTP.

---

## 0. Przygotowanie środowiska

- [ ] **0.1** Utworzyć strukturę katalogów: `birdtracker-server/app/`
- [ ] **0.2** Stworzyć `requirements.txt` z zależnościami: `fastapi`, `uvicorn[standard]`, `neo4j`, `python-dotenv`, `pydantic[email-validator]`, `pydantic-settings`
- [ ] **0.3** Stworzyć wirtualne środowisko i zainstalować pakiety
- [ ] **0.4** Stworzyć plik `.env` z danymi Neo4j, SMTP i parametrami algorytmu (`V_MAX_KMH`, `SILENCE_WINDOW_HOURS`, `BEARING_TOLERANCE_DEG`)
- [ ] **0.5** Stworzyć `app/__init__.py`
- [ ] **0.6** Napisać i uruchomić `test_imports.py` — weryfikacja, że wszystkie pakiety importują się poprawnie

---

## 1. Konfiguracja

- [ ] **1.1** Stworzyć `app/config.py` — klasa `Settings` z `pydantic_settings.BaseSettings`, odczyt z `.env`
- [ ] **1.2** Eksportować globalny obiekt `settings`
- [ ] **1.3** Napisać `test_config.py`:
  - [ ] Sprawdzenie wartości domyślnych (bez `.env`)
  - [ ] Nadpisanie zmiennych środowiskowych i weryfikacja odczytu

---

## 2. Narzędzia geograficzne

- [ ] **2.1** Stworzyć `app/utils.py` z trzema funkcjami:
  - [ ] `haversine_distance(lat1, lon1, lat2, lon2)` — odległość wielkiego koła
  - [ ] `calculate_bearing(lat1, lon1, lat2, lon2)` — azymut w stopniach (0° = N)
  - [ ] `angle_difference(a, b)` — różnica kątowa [0, 180]
- [ ] **2.2** Napisać `test_utils.py`:
  - [ ] Odległość tego samego punktu = 0
  - [ ] Warszawa → Kraków ≈ 250 km
  - [ ] Azymut równik → biegun = 0°
  - [ ] `angle_difference(350, 10)` = 20°

---

## 3. Klient Neo4j i inicjalizacja bazy

- [ ] **3.1** Stworzyć `app/neo4j_client.py`:
  - [ ] Inicjalizacja `GraphDatabase.driver` z konfiguracji
  - [ ] Funkcja `get_db()` zwracająca sesję
- [ ] **3.2** Stworzyć `init_db.py` — skrypt tworzący unikalne ograniczenia i indeksy:
  - [ ] `flock_id` (uniqueness na `Flock.id`)
  - [ ] `report_id` (uniqueness na `Report.id`)
  - [ ] `coordinator_email` (uniqueness na `Coordinator.email`)
  - [ ] `city_name` (uniqueness na `City.name`)
  - [ ] Indeks na `Report.location` i `City.location`
- [ ] **3.3** Napisać `test_neo4j_client.py`:
  - [ ] Weryfikacja łączności (`verify_connectivity`)
  - [ ] Wywołanie `init_schema()` i sprawdzenie indeksów
  - [ ] CRUD testowego węzła

---

## 4. Modele Pydantic

- [ ] **4.1** Stworzyć `app/models.py`:
  - [ ] `ReportRequest` — `latitude`, `longitude`, `timestamp`, `coordinator_email` (z walidacją email i brakiem przyszłego timestampu)
  - [ ] `ReportResponse` — `report_id`, `flock_id`, `message`
- [ ] **4.2** Napisać `test_models.py`:
  - [ ] Poprawne dane → obiekt utworzony
  - [ ] Brak wymaganego pola → `ValidationError`
  - [ ] Szerokość poza [-90, 90] → `ValidationError`
  - [ ] Nieprawidłowy email → `ValidationError`
  - [ ] Timestamp w przyszłości → `ValidationError`

---

## 5. Logika biznesowa (serce systemu)

- [ ] **5.0** Stworzyć `cities.csv` (name, lat, lon) — stolice Europy jako dane testowe
- [ ] **5.1** Stworzyć `load_cities.py` — skrypt ładowania miast do Neo4j przez `MERGE`
- [ ] **5.2** Stworzyć `app/services.py` z funkcjami:
  - [ ] `identify_or_create_flock(lat, lon, timestamp)` — algorytm:
    - Szuka istniejących stad w oknie `SILENCE_WINDOW_HOURS`
    - Filtruje po `haversine_distance <= V_MAX_KMH * time_delta_hours`
    - Wybiera najbliższe stado (kandydat z najmniejszą odległością)
    - Jeśli brak kandydatów → tworzy nowe stado z `uuid4()`
    - Zwraca `(flock_id, is_new)`
  - [ ] `add_report_and_get_flock_info(flock_id, lat, lon, timestamp, coordinator_email)` —:
    - Dodaje węzeł `Report` z relacją `(:Flock)-[:HAS_REPORT]->(:Report)`
    - Aktualizuje relację `LAST_REPORT` na Flock
    - Tworzy węzeł `Coordinator` z relacją `(:Flock)-[:NOTIFIED_OF]->(:Coordinator)`
    - Zwraca `(report_id, last_2_points)`
  - [ ] `predict_city(lat, lon, bearing)` —:
    - Pobiera wszystkie miasta z Neo4j
    - Oblicza azymut do każdego miasta
    - Filtruje po `angle_difference(bearing, city_bearing) <= BEARING_TOLERANCE_DEG`
    - Zwraca najbliższe miasto (dystans + ETA) lub `None`
- [ ] **5.3** Napisać `test_services.py` (z osobną bazą testową `NEO4J_TEST_URI`):
  - [ ] Fixture: czyszczony bazie + testowe miasta przed każdym testem
  - [ ] Nowe stado (pusta baza) → `is_new = True`
  - [ ] Globalna cisza (ostatni raport > 10h) → nowe stado
  - [ ] Dopasowanie do istniejącego (50 km, 1h) → `is_new = False`
  - [ ] Przekroczenie Vmax (500 km, 2h) → nowe stado
  - [ ] Wybór najbliższego (10 km vs 20 km)
  - [ ] `add_report_and_get_flock_info` — raport dodany, relacja zaktualizowana, koordynator stworzony, 2 punkty zwrócone
  - [ ] Predykcja miasta — filtr po kącie, wybór najbliższego

---

## 6. Powiadomienia e-mail

- [ ] **6.1** Stworzyć `app/notifications.py`:
  - [ ] `send_notification(flock_id, report_id, lat, lon, city_name, eta_hours)`
  - [ ] Odczyt koordynatorów z Neo4j (`Coordinator` węzły powiązane z `Flock`)
  - [ ] Budowanie treści wiadomości (SMTP)
  - [ ] Obsługa braku koordynatorów (bez błędu)
- [ ] **6.2** Napisać `test_notifications.py`:
  - [ ] Mock `smtplib.SMTP` — weryfikacja odbiorcy i treści
  - [ ] Brak koordynatorów → brak błędu

---

## 7. Aplikacja FastAPI

- [ ] **7.1** Stworzyć `app/main.py`:
  - [ ] `POST /api/report` — endpoint przyjmujący `ReportRequest`, wywołujący `services` i `notifications`, zwracający `ReportResponse`
  - [ ] `GET /health` — zwraca `{"status": "ok"}`
- [ ] **7.2** Napisać `test_main.py` z `TestClient`:
  - [ ] Poprawne żądanie POST → 200 + poprawna odpowiedź
  - [ ] Niepoprawne dane → 422
  - [ ] `GET /health` → 200
  - [ ] Mock `send_notification` — brak wysyłania rzeczywistych e-maili

---

## 8. Testy integracyjne i uruchomienie

- [ ] **8.1** Uruchomić serwer: `uvicorn app.main:app --reload`
- [ ] **8.2** Uruchomić pełną suite: `pytest` — wszystkie testy muszą przejść
- [ ] **8.3** Scenariusz integracyjny (curl / skrypt):
  - [ ] Wyczyść Neo4j
  - [ ] Zgłoszenie 1 (Warszawa) → nowe stado
  - [ ] Zgłoszenie 2 (50 km N, +30 min) → to samo stado
  - [ ] Sprawdzenie bazy: 2 raporty, `LAST_REPORT`, 1 koordynator
  - [ ] Zgłoszenie 3 (500 km dalej, +1h) → nowe stado (przekroczenie Vmax)
  - [ ] Predykcja miasta (np. Gdańsk) przy kierunku północnym

---

## Struktura plików (końcowa)

```
birdtracker-server/
├── .env
├── .gitignore
├── cities.csv
├── init_db.py
├── load_cities.py
├── requirements.txt
├── test_config.py
├── test_imports.py
├── test_main.py
├── test_models.py
├── test_neo4j_client.py
├── test_notifications.py
├── test_services.py
├── test_utils.py
├── venv/
└── app/
    ├── __init__.py
    ├── config.py
    ├── main.py
    ├── models.py
    ├── neo4j_client.py
    ├── notifications.py
    ├── services.py
    └── utils.py
```

---

## Uwagi

- Każdy krok kończy się napisaniem testów i ich uruchomieniem.
- Do testów Neo4j używać osobnej instancji / URI (`NEO4J_TEST_URI`), aby nie zaśmiecać produkcji.
- Bezpieczeństwo (autoryzacja, middleware) dodane w osobnej iteracji — na tym etapie pomijamy.
