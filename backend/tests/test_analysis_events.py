from app.models import AnalysisJobEvent


def test_analysis_job_event_model_exposes_lifecycle_fields():
    event = AnalysisJobEvent(
        analysis_job_id="00000000-0000-0000-0000-000000000001",
        event_type="started",
        status="running",
        message="Worker started processing the analysis job.",
    )

    assert event.event_type == "started"
    assert event.status == "running"
    assert event.message
    assert len(event.message) <= 500
