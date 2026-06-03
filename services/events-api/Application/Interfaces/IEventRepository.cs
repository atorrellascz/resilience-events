using EventsApi.Domain.Entities;

namespace EventsApi.Application.Interfaces;

/// <summary>
/// Puerto de persistencia. La capa Application define ESTA interfaz;
/// Infrastructure la implementa (con EF Core/SQL Server) en otro anillo.
/// Application NO sabe qué hay detrás: podría ser SQL Server, Postgres o un mock.
/// </summary>
public interface IEventRepository
{
    Task<Event> AddAsync(Event evt, CancellationToken ct = default);
    Task<Event?> GetByIdAsync(Guid id, CancellationToken ct = default);
    Task<IReadOnlyList<Event>> ListAsync(int limit, CancellationToken ct = default);

    // Para el /ready: ¿la base responde? (lo usaremos en el health check real)
    Task<bool> CanConnectAsync(CancellationToken ct = default);
}