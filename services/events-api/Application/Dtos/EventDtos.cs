namespace EventsApi.Application.Dtos;

/// <summary>What the client SENDS to create an event (input).</summary>
public record CreateEventRequest(
    string Source,
    string Severity,
    string Message,
    DateTimeOffset? OccurredAt   // optional: if not sent, we use "now"
);

/// <summary>What the service RETURNS (output). We do NOT expose the entity directly.</summary>
public record EventResponse(
    Guid Id,
    string Source,
    string Severity,
    string Message,
    DateTimeOffset OccurredAt,
    DateTimeOffset RecordedAt
);