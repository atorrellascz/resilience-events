using EventsApi.Application.Interfaces;
using EventsApi.Domain.Entities;
using EventsApi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace EventsApi.Infrastructure.Repositories;

/// <summary>
/// Implementa IEventRepository usando EF Core + SQL Server.
/// Application definió el contrato; aquí lo cumplimos. Si cambiáramos a Postgres,
/// solo esta clase y el DbContext cambian — la lógica de negocio NO se toca.
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
            .AsNoTracking()                       // solo lectura: no rastrea cambios (más rápido)
            .FirstOrDefaultAsync(x => x.Id == id, ct);

    public async Task<IReadOnlyList<Event>> ListAsync(int limit, CancellationToken ct = default) =>
        await _db.Events
            .AsNoTracking()
            .OrderByDescending(x => x.OccurredAt)
            .Take(limit)
            .ToListAsync(ct);

    // Chequeo de salud real para el /ready: ¿SQL Server responde?
    public async Task<bool> CanConnectAsync(CancellationToken ct = default) =>
        await _db.Database.CanConnectAsync(ct);
}