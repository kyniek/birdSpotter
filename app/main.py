"""FastAPI application for BirdTracker."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .models import ReportRequest, ReportResponse
from .services import (
    identify_or_create_flock,
    add_report_and_get_flock_info,
    predict_cities,
    count_reports_for_flock,
    get_nearest_city,
    should_send_notification,
)
from .utils import calculate_bearing, haversine_distance
from .notifications import send_notification
from .lifecycle import init_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database on startup."""
    init_database()
    yield


app = FastAPI(title="BirdTracker API", lifespan=lifespan)


@app.post("/api/report", response_model=ReportResponse)
def submit_report(report: ReportRequest):
    """Accept a bird sighting report and route it to the correct flock."""
    # 1. Identify flock
    flock_id, is_new = identify_or_create_flock(
        report.latitude, report.longitude, report.timestamp
    )

    # 2. Add report and get flock info
    report_id, last_points = add_report_and_get_flock_info(
        flock_id,
        report.latitude,
        report.longitude,
        report.timestamp,
        report.coordinator_email,
        skip_create=is_new,
    )

    # 3. Predict cities
    predicted_cities: list[tuple[str, float]] = []
    eta_hours: float | None = None
    if len(last_points) >= 2:
        lat1, lon1 = last_points[0]["location"]
        lat2, lon2 = last_points[1]["location"]
        bearing = calculate_bearing(lat1, lon1, lat2, lon2)
        predicted_cities = predict_cities(lat2, lon2, bearing)
        if predicted_cities:
            # Use closest city for ETA calculation
            city_name, dist_km = predicted_cities[0]
            dt_hrs = (
                last_points[0]["timestamp"] - last_points[1]["timestamp"]
            ).total_seconds() / 3600
            if dt_hrs > 0:
                speed = haversine_distance(lat1, lon1, lat2, lon2) / dt_hrs
                if speed > 0:
                    eta_hours = dist_km / speed

    # 4. Determine whether to send notification
    #    Get nearest city for current report
    current_city = get_nearest_city(report.latitude, report.longitude)

    #    Get nearest city for the previous report (if any exists)
    last_report_city: str | None = None
    if len(last_points) >= 2:
        prev_lat, prev_lon = last_points[1]["location"]
        last_report_city = get_nearest_city(prev_lat, prev_lon)

    #    Count total reports for this flock
    report_count = count_reports_for_flock(flock_id)

    #    Decide
    notify = should_send_notification(
        flock_id, is_new, report_count, current_city, last_report_city,
    )

    if notify:
        send_notification(
            flock_id, report_id, report.latitude, report.longitude,
            predicted_cities, eta_hours,
        )

    return ReportResponse(
        report_id=report_id,
        flock_id=flock_id,
        message=f"{'Nowe stado' if is_new else 'Dołączono'} {flock_id[:8]}",
        predicted_cities=predicted_cities,
    )


@app.get("/health")
def health():
    return {"status": "ok"}
