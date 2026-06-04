namespace EventsApi.Domain.Entities;

/// <summary>
/// Un registro de evento operacional — la entidad central del dominio.
/// C# puro: NO conoce EF Core, ni HTTP, ni ninguna infraestructura.
/// </summary>
public class Event
{
    public Guid Id { get; private set; }
    public string Source { get; private set; } = string.Empty;
    public string Severity { get; private set; } = string.Empty;
    public string Message { get; private set; } = string.Empty;
    public DateTimeOffset OccurredAt { get; private set; }
    public DateTimeOffset RecordedAt { get; private set; }

    // Constructor privado sin parámetros: requerido por EF Core para materializar
    // desde la DB. Privado para que NADIE más cree un Event inválido por aquí.
    private Event() { }

    // Fábrica: la ÚNICA forma de crear un Event. Garantiza un objeto válido
    // desde su nacimiento (invariantes del dominio protegidas).
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