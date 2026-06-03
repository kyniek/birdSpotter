Oto instrukcja implementacji serwera (Python + FastAPI + Neo4j) dla agenta – **bez warstwy zabezpieczeń** (te dodamy później). Po każdym kroku agent ma stworzyć i uruchomić testy weryfikujące poprawność wdrożonych funkcji.

---

## Założenia ogólne
- Serwer przyjmuje zgłoszenia przez REST API, przechowuje je w Neo4j, przypisuje do stad na podstawie czasoprzestrzeni, prognozuje trasę i wysyła e‑maile do koordynatorów.
- Środowisko: Python 3.11+, wirtualne środowisko, menedżer pakietów pip.
- Baza danych: Neo4j (lokalna lub AuraDB) – potrzebny działający serwer.
- Testy piszemy od razu, każdy krok kończy się testem.
- Kod znajduje się w katalogu `birdtracker-server/app/`.

---

## Krok 0: Struktura projektu i zależności

1. Utwórz katalog `birdtracker-server` a w nim podkatalog `app`.
2. W głównym katalogu utwórz plik `requirements.txt` z zawartością:
```
fastapi
uvicorn[standard]
neo4j
python-dotenv
pydantic[email-validator]
```
3. Utwórz wirtualne środowisko i zainstaluj zależności:
```bash
python -m venv venv
source venv/bin/activate   # na Windows: venv\Scripts\activate
pip install -r requirements.txt
```
4. Utwórz plik `.env` (tymczasowo z fikcyjnymi danymi – podmienisz później):
```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=Qwerty1234
IMAP_HOST = "imap.gmail.com"
SMTP_PORT=587
SMTP_USER=k.p.nielepkowicz@gmail.com
```
SMTP_PASSWORD:  [check password in this file](./pass.md)
```
V_MAX_KMH=100
SILENCE_WINDOW_HOURS=10
BEARING_TOLERANCE_DEG=30
```
5. Utwórz `app/__init__.py` (pusty).

**Testy** – na tym etapie sprawdź, czy import `fastapi`, `neo4j` itp. działa. Utwórz plik `test_imports.py`:
```python
def test_import_fastapi():
    import fastapi
    assert fastapi.__version__

def test_import_neo4j():
    import neo4j
    assert neo4j.__version__
```
Uruchom: `pytest test_imports.py` (zainstaluj wcześniej pytest: `pip install pytest`).

---

## Krok 1: Konfiguracja aplikacji (`app/config.py`)

Plik `app/config.py`:
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    v_max_kmh: float = 100.0
    silence_window_hours: int = 10
    bearing_tolerance_deg: float = 30.0

    class Config:
        env_file = ".env"

settings = Settings()
```

**Testy** – utwórz `test_config.py`:
- Sprawdź, czy obiekt `settings` ładuje wartości domyślne (bez pliku .env).
- Nadpisz zmienne środowiskowe w teście i sprawdź odczyt.
```python
import os
from app.config import Settings

def test_default_values():
    # tymczasowo wyczyść env
    for key in list(os.environ):
        if key.startswith("NEO4J_") or key.startswith("V_MAX"):
            del os.environ[key]
    s = Settings(_env_file=None)  # bez pliku
    assert s.v_max_kmh == 100.0

def test_env_override(monkeypatch):
    monkeypatch.setenv("V_MAX_KMH", "120")
    s = Settings(_env_file=None)
    assert s.v_max_kmh == 120.0
```

---

## Krok 2: Narzędzia geograficzne (`app/utils.py`)

Zaimplementuj funkcje (bez zewnętrznych bibliotek, czysta trygonometria):
```python
import math

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0  # km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def calculate_bearing(lat1, lon1, lat2, lon2):
    """Azymut z pkt1 do pkt2 (0° = N, 90° = E)."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2) -
         math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    bearing = math.atan2(x, y)
    return (math.degrees(bearing) + 360) % 360

def angle_difference(a, b):
    """Różnica kątowa w stopniach [0,180]."""
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)
```

**Testy** – `test_utils.py`:
- Sprawdź odległość między tymi samymi punktami (powinna być 0).
- Dla znanych współrzędnych (np. Warszawa–Kraków) porównaj z przybliżoną odległością (ok. 250 km).
- Dla azymutu: między punktem na równiku a biegunem północnym azymut powinien być 0°.
- angle_difference: sprawdź kilka par kątów, w tym owijanie 350° i 10° (różnica 20°).

---

## Krok 3: Klient Neo4j i inicjalizacja bazy (`app/neo4j_client.py` + skrypt `init_db.py`)

`app/neo4j_client.py`:
```python
from neo4j import GraphDatabase
from .config import settings

driver = GraphDatabase.driver(
    settings.neo4j_uri,
    auth=(settings.neo4j_user, settings.neo4j_password)
)

def get_db():
    return driver.session(database="neo4j")
```

Skrypt `init_db.py` (główny katalog):
```python
from app.neo4j_client import get_db

def init_schema():
    with get_db() as session:
        session.run("CREATE CONSTRAINT flock_id IF NOT EXISTS FOR (f:Flock) REQUIRE f.id IS UNIQUE")
        session.run("CREATE CONSTRAINT report_id IF NOT EXISTS FOR (r:Report) REQUIRE r.id IS UNIQUE")
        session.run("CREATE CONSTRAINT coordinator_email IF NOT EXISTS FOR (c:Coordinator) REQUIRE c.email IS UNIQUE")
        session.run("CREATE CONSTRAINT city_name IF NOT EXISTS FOR (c:City) REQUIRE c.name IS UNIQUE")
        session.run("CREATE INDEX report_location IF NOT EXISTS FOR (r:Report) ON (r.location)")
        session.run("CREATE INDEX city_location IF NOT EXISTS FOR (c:City) ON (c.location)")
        print("Schema created successfully.")

if __name__ == "__main__":
    init_schema()
```

**Testy** – `test_neo4j_client.py` (wymaga działającej bazy, możesz użyć testowej bazy lokalnie):
- Sprawdź, czy połączenie działa: `driver.verify_connectivity()`.
- Wywołaj `init_schema()` i sprawdź, czy zapytanie o indeksy nie rzuca błędów.
- Dodaj i odczytaj przykładowy węzeł testowy, potem usuń.

---

## Krok 4: Modele Pydantic (`app/models.py`)

```python
from pydantic import BaseModel, EmailStr, Field, model_validator
from datetime import datetime, timezone

class ReportRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    coordinator_email: EmailStr

    @model_validator(mode='after')
    def check_timestamp_not_future(self):
        if self.timestamp > datetime.now(timezone.utc):
            raise ValueError('Timestamp nie może być w przyszłości')
        return self

class ReportResponse(BaseModel):
    report_id: str
    flock_id: str
    message: str
```

**Testy** – `test_models.py`:
- Poprawne dane → tworzy obiekt.
- Brak wymaganego pola → `ValidationError`.
- Szerokość poza zakresem → `ValidationError`.
- Nieprawidłowy e-mail → błąd.
- Timestamp w przyszłości → błąd walidacji.

---

## Krok 5: Logika biznesowa (`app/services.py`)

To najważniejszy krok. Zaimplementuj funkcje:

- `identify_or_create_flock(lat, lon, timestamp)` → zwraca `(flock_id, is_new)`
- `add_report_and_get_flock_info(flock_id, lat, lon, timestamp, coordinator_email)` → zwraca `(report_id, lista_ostatnich_2_punktów)`
- `predict_city(lat, lon, bearing)` → zwraca `(nazwa_miasta, dystans_km)` lub `None`

**Wymagane importy**: użyj `uuid.uuid4()` do ID, Neo4j z `get_db()`, konfiguracji, utils.

**Uwaga**: Funkcja `predict_city` niech pobiera miasta z bazy, oblicza azymut do każdego i wybiera najbliższe w tolerancji kąta. Najpierw załaduj dane miast (patrz Krok 5a).

**Przed implementacją predykcji** musisz mieć miasta w bazie. Utwórz skrypt `load_cities.py`, który wczyta plik CSV (np. `cities.csv` z kolumnami: name,lat,lon) i za pomocą MERGE doda węzły City z lokalizacją. Użyj go do załadowania testowego zestawu miast (np. stolice Europy).

**Implementacja `services.py`** – podziel na kilka funkcji pomocniczych, trzymaj się wcześniej podanego algorytmu (Vmax, okno ciszy, najbliższy kandydat).

**Testy** – `test_services.py` (najobszerniejsze):

1. **Przygotowanie**: Stwórz fixture, który czyści bazę przed każdym testem i dodaje testowe miasta.
2. **Identyfikacja nowego stada**: Wywołaj `identify_or_create_flock` z dowolnymi współrzędnymi, gdy baza jest pusta → `is_new = True`, zwrócone ID.
3. **Globalna cisza**: Dodaj do bazy stado z ostatnim raportem starszym niż 10h. Nowe zgłoszenie → nowe stado.
4. **Dopasowanie do istniejącego**: Wstaw stado z ostatnim raportem (współrzędne A) sprzed 1h. Nowe zgłoszenie w odległości 50 km → przypisane do tego stada (spełnia Vmax 100 km/h). Sprawdź `is_new = False`.
5. **Brak kandydatów (przekroczona Vmax)**: Stado z ostatnim punktem 500 km od nowego, czas 2h → `dist > Vmax*dt`, więc nowe stado.
6. **Wybór najbliższego**: Dwa stad w zasięgu, jedno 10 km, drugie 20 km → wybór bliższego.
7. **`add_report_and_get_flock_info`**: Sprawdź, czy raport został dodany, relacja `LAST_REPORT` zaktualizowana, koordynator stworzony, zwrócone ostatnie 2 punkty.
8. **Predykcja miasta**: Dodaj dwa punkty stada (kierunek np. 45°) i kilka miast, niektóre pod kątem <30°, niektóre >30°. Sprawdź, czy wybrane miasto jest najbliższe w sektorze.

Użyj osobnej bazy testowej (np. zmienna środowiskowa `NEO4J_TEST_URI`), aby nie zaśmiecać głównej.

---

## Krok 6: Powiadomienia e‑mail (`app/notifications.py`)

Funkcja `send_notification(flock_id, report_id, lat, lon, city_name=None, eta_hours=None)`. Wykorzystaj `smtplib`, odczytaj adresy koordynatorów z Neo4j, wyślij wiadomość.

**Testy** – `test_notifications.py`:
- Uruchom lokalny serwer SMTP (np. `smtpd` z Pythona) lub mockuj `smtplib.SMTP`. Sprawdź, czy wysłana wiadomość trafia do właściwych odbiorców, zawiera ID stada.
- Upewnij się, że brak koordynatorów nie powoduje błędu.

---

## Krok 7: Aplikacja FastAPI (`app/main.py`)

Zdefiniuj endpointy:
- `POST /api/report` – przyjmuje JSON `ReportRequest`, zwraca `ReportResponse`.
- `GET /health` – status.

W ciele endpointu użyj wcześniejszych serwisów. **Nie dodawaj middleware'ów bezpieczeństwa.** Na razie tylko prosta logika.

Przykład:
```python
from fastapi import FastAPI, HTTPException
from .models import ReportRequest, ReportResponse
from .services import identify_or_create_flock, add_report_and_get_flock_info, predict_city
from .utils import calculate_bearing, haversine_distance
from .notifications import send_notification

app = FastAPI(title="BirdTracker API")

@app.post("/api/report", response_model=ReportResponse)
async def submit_report(report: ReportRequest):
    # identyfikacja
    flock_id, is_new = await identify_or_create_flock(
        report.latitude, report.longitude, report.timestamp
    )
    # dodanie raportu
    report_id, last_points = await add_report_and_get_flock_info(
        flock_id, report.latitude, report.longitude,
        report.timestamp, report.coordinator_email
    )
    # predykcja
    city_name, eta_hours = None, None
    if len(last_points) >= 2:
        lat1, lon1 = last_points[0]["location"].y, last_points[0]["location"].x
        lat2, lon2 = last_points[1]["location"].y, last_points[1]["location"].x
        bearing = calculate_bearing(lat1, lon1, lat2, lon2)
        pred = predict_city(lat2, lon2, bearing)
        if pred:
            city_name, dist_km = pred
            dt_hrs = (last_points[1]["timestamp"] - last_points[0]["timestamp"]).total_seconds() / 3600
            if dt_hrs > 0:
                speed = haversine_distance(lat1, lon1, lat2, lon2) / dt_hrs
                if speed > 0:
                    eta_hours = dist_km / speed
    # powiadomienia
    await send_notification(flock_id, report_id, report.latitude, report.longitude,
                            city_name, eta_hours)
    return ReportResponse(
        report_id=report_id,
        flock_id=flock_id,
        message=f"{'Nowe stado' if is_new else 'Dołączono'} {flock_id[:8]}"
    )

@app.get("/health")
def health():
    return {"status": "ok"}
```

**Testy** – `test_main.py` z użyciem `fastapi.testclient.TestClient`:
- Wystartuj aplikację testową (bez pełnego serwera).
- Wyślij poprawne żądanie POST, sprawdź status 200 i zawartość odpowiedzi.
- Wyślij niepoprawne dane (np. zła szerokość) – oczekuj 422.
- Sprawdź, czy health działa.

Uwzględnij mocki dla `send_notification`, aby faktycznie nie wysyłać e‑maili.

---

## Krok 8: Końcowe testy integracyjne i uruchomienie

Po napisaniu wszystkich modułów i testów:
- Uruchom pełną aplikację `uvicorn app.main:app --reload`.
- Wykonaj kilka żądań curl (lub skrypt testowy), symulując sekwencję zgłoszeń i obserwuj logi.
- Upewnij się, że wszystkie testy przechodzą (`pytest`).

**Scenariusz integracyjny (ręczny/skrypt)**:
1. Wyczyść bazę Neo4j.
2. Wyślij 1. zgłoszenie (np. Warszawa, email `a@b.com`) → nowe stado.
3. Wyślij 2. zgłoszenie (50 km na północ, 30 min później) → powinno zostać przypisane do tego samego stada.
4. Sprawdź w bazie: stado ma dwa raporty, relację `LAST_REPORT`, jednego koordynatora.
5. Wyślij 3. zgłoszenie 500 km dalej, ale w czasie 1h (prędkość 500 km/h > Vmax) → nowe stado.
6. Po dodaniu miast testowych (np. Gdańsk na północy), trzecie zgłoszenie z kierunkiem północnym powinno wskazać Gdańsk jako prognozę.

---

Agent powinien postępować dokładnie według powyższych kroków, po każdym kroku tworząc plik z testami i upewniając się, że przechodzą. W razie problemów – debugować i poprawiać.