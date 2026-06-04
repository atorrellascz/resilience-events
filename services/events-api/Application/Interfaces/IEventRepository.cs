using EventsApi.Domain.Entities;

namespace EventsApi.Application.Interfaces;

/// <summary>
/// Persistence port. The Application layer defines THIS interface;
/// Infrastructure implements it (with EF Core/SQL Server) in another ring.
/// Application does NOT know what's behind it: could be SQL Server, Postgres, or a mock.
/// </summary>
public interface IEventRepository
{
    Task<Event> AddAsync(Event evt, CancellationToken ct = default);
    Task<Event?> GetByIdAsync(Guid id, CancellationToken ct = default);
    Task<IReadOnlyList<Event>> ListAsync(int limit, CancellationToken ct = default);

    // For /ready: does the database respond? (used in the real health check)
    Task<bool> CanConnectAsync(CancellationToken ct = default);
}