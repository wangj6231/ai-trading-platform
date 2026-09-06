from app.schemas.structure import StructureBreakEvent


def structure_event_reference(event: StructureBreakEvent) -> str:
    """Return the stable cross-engine identifier for a structure event."""

    return (
        f"{event.type.value}:{event.direction.value}:{event.timestamp.isoformat()}:"
        f"{event.broken_structure_id}"
    )
