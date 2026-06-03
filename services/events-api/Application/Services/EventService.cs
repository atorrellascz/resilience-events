using EventsApi.Application.Dtos;
using EventsApi.Application.Interfaces;
using EventsApi.Domain.Entities;

namespace EventsApi.Application.Services;

public interface IEventService
{
    Task<EventResponse> CreateAsync(CreateEventRequest req, CancellationToken ct = default);
    Task<EventResponse?> GetAsync(Guid id, CancellationToken ct = default);
    Task<IReadOnlyList<EventResponse>> ListAsync(int limit, CancellationToken ct = default);
}

public class EventService : IEventService
{
    private readonly IEventRepository _repo;   // depende de la ABSTRACCIÓN, no de EF Core

    // Inyección por constructor: el repo concreto se inyecta desde afuera (DI).
    public EventService(IEventRepository repo) => _repo = repo;

    public async Task<EventResponse> CreateAsync(CreateEventRequest req, CancellationToken ct = default)
    {
        // La fábrica del dominio valida y crea un Event válido por construcción.
        var evt = Event.Create(
            req.Source,
            req.Severity,
            req.Message,
            req.OccurredAt ?? DateTimeOffset.UtcNow);

        var saved = await _repo.AddAsync(evt, ct);
        return ToResponse(saved);
    }

    public async Task<EventResponse?> GetAsync(Guid id, CancellationToken ct = default)
    {
        var evt = await _repo.GetByIdAsync(id, ct);
        return evt is null ? null : ToResponse(evt);
    }

    public async Task<IReadOnlyList<EventResponse>> ListAsync(int limit, CancellationToken ct = default)
    {
        if (limit is < 1 or > 200) limit = 50;   // cota defensiva: nunca un query ilimitado
        var events = await _repo.ListAsync(limit, ct);
        return events.Select(ToResponse).ToList();
    }

    // Mapeo entidad -> DTO, en un solo lugar (DRY).
    private static EventResponse ToResponse(Event e) =>
        new(e.Id, e.Source, e.Severity, e.Message, e.OccurredAt, e.RecordedAt);
}