namespace EventsApi.Domain.Entities;

/// <summary>
/// An operational event record — the central entity of the domain.
/// Pure C#: it knows NOTHING about EF Core, HTTP, or any infrastructure.
/// </summary>
public class Event
{
    public Guid Id { get; private set; }
    public string Source { get; private set; } = string.Empty;
    public string Severity { get; private set; } = string.Empty;
    public string Message { get; private set; } = string.Empty;
    public DateTimeOffset OccurredAt { get; private set; }
    public DateTimeOffset RecordedAt { get; private set; }

    // Private parameterless constructor: required by EF Core to materialize
    // from the DB. Private so that NO ONE else creates an invalid Event this way.
    private Event() { }

    // Factory: the ONLY way to create an Event. Guarantees a valid object
    // from birth (domain invariants protected).
    public static Event Create(string source, string severity, string message, DateTimeOffset occurredAt)
    {
        if (string.IsNullOrWhiteSpace(source))
            throw new ArgumentException("Source is required.", nameof(source));
        if (string.IsNullOrWhiteSpace(message))
            throw new ArgumentException("Message is required.", nameof(message));

        return new Event
        {
            Id         = Guid.NewGuid(),
            Source     = source.Trim(),
            Severity   = NormalizeSeverity(severity),
            Message    = message.Trim(),
            OccurredAt = occurredAt,
            RecordedAt = DateTimeOffset.UtcNow
        };
    }

    private static string NormalizeSeverity(string severity)
    {
        var s = (severity ?? "").Trim().ToLowerInvariant();
        return s is "info" or "warning" or "critical" ? s : "info";
    }
}