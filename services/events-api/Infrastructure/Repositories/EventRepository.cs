using EventsApi.Application.Interfaces;
using EventsApi.Domain.Entities;
using EventsApi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace EventsApi.Infrastructure.Repositories;

/// <summary>
/// Implements IEventRepository using EF Core + SQL Server.
/// Application defined the contract; here we fulfill it. If we switched to Postgres,
/// only this class and the DbContext change — the business logic is NOT touched.
/// </summary>
public class EventRepository : IEventRepository
{
    private readonly EventsDbContext _db;

    public EventRepository(EventsDbContext db) => _db = db;

    public async Task<Event> AddAsync(Event evt, CancellationToken ct = default)
    {
        _db.Events.Add(evt);
        await _db.SaveChangesAsync(ct);
        return evt;
    }

    public async Task<Event?> GetByIdAsync(Guid id, CancellationToken ct = default) =>
        await _db.Events
            .AsNoTracking()                       // read-only: does not track changes (faster)
            .FirstOrDefaultAsync(x => x.Id == id, ct);

    public async Task<IReadOnlyList<Event>> ListAsync(int limit, CancellationToken ct = default) =>
        await _db.Events
            .AsNoTracking()
            .OrderByDescending(x => x.OccurredAt)
            .Take(limit)
            .ToListAsync(ct);

    // Real health check for /ready: does SQL Server respond?
    public async Task<bool> CanConnectAsync(CancellationToken ct = default) =>
        await _db.Database.CanConnectAsync(ct);
}