"""FastAPI application for BirdTracker."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .models import ReportRequest, ReportResponse
from .services import (
    identify_or_create_flock,
    add_report_and_get_flock_info,
    predict_city,
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

    # 3. Predict city
    city_name: str | None = None
    eta_hours: float | None = None
    if len(last_points) >= 2:
        lat1, lon1 = last_points[0]["location"]
        lat2, lon2 = last_points[1]["location"]
        bearing = calculate_bearing(lat1, lon1, lat2, lon2)
        pred = predict_city(lat2, lon2, bearing)
        if pred:
            city_name, dist_km = pred
            dt_hrs = (
                last_points[0]["timestamp"] - last_points[1]["timestamp"]
            ).total_seconds() / 3600
            if dt_hrs > 0:
                speed = haversine_distance(lat1, lon1, lat2, lon2) / dt_hrs
                if speed > 0:
                    eta_hours = dist_km / speed

    # 4. Send notification
    send_notification(
        flock_id, report_id, report.latitude, report.longitude,
        city_name, eta_hours,
    )

    return ReportResponse(
        report_id=report_id,
        flock_id=flock_id,
        message=f"{'Nowe stado' if is_new else 'Dołączono'} {flock_id[:8]}",
    )


@app.get("/health")
def health():
    return {"status": "ok"}
