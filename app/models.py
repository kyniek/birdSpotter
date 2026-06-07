from pydantic import BaseModel, EmailStr, Field, model_validator
from datetime import datetime, timezone


class ReportRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    coordinator_email: EmailStr

    @model_validator(mode="after")
    def check_timestamp_not_future(self):
        if self.timestamp > datetime.now(timezone.utc):
            raise ValueError("Timestamp nie może być w przyszłości")
        return self


class ReportResponse(BaseModel):
    report_id: str
    flock_id: str
    message: str
