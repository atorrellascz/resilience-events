namespace EventsApi.Application.Dtos;

/// <summary>Lo que el cliente ENVÍA para crear un evento (entrada).</summary>
public record CreateEventRequest(
    string Source,
    string Severity,
    string Message,
    DateTimeOffset? OccurredAt   // opcional: si no lo manda, usamos "ahora"
);

/// <summary>Lo que el servicio DEVUELVE (salida). NO exponemos la entidad directa.</summary>
public record EventResponse(
    Guid Id,
    string Source,
    string Severity,
    string Message,
    DateTimeOffset OccurredAt,
    DateTimeOffset RecordedAt
);