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
    private readonly IEventRepository _repo;   // depends on the ABSTRACTION, not on EF Core

    // Constructor injection: the concrete repo is injected from outside (DI).
    public EventService(IEventRepository repo) => _repo = repo;

    public async Task<EventResponse> CreateAsync(CreateEventRequest req, CancellationToken ct = default)
    {
        // The domain factory validates and creates an Event that is valid by construction.
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
        if (limit is < 1 or > 200) limit = 50;   // defensive cap: never an unbounded query
        var events = await _repo.ListAsync(limit, ct);
        return events.Select(ToResponse).ToList();
    }

    // Entity -> DTO mapping, in a single place (DRY).
    private static EventResponse ToResponse(Event e) =>
        new(e.Id, e.Source, e.Severity, e.Message, e.OccurredAt, e.RecordedAt);
}