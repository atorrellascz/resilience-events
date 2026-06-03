using EventsApi.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace EventsApi.Infrastructure.Persistence;

/// <summary>
/// Puente entre el dominio y SQL Server. Vive en Infrastructure porque
/// conoce EF Core — un detalle que el dominio jamás debe ver.
/// </summary>
public class EventsDbContext : DbContext
{
    public EventsDbContext(DbContextOptions<EventsDbContext> options) : base(options) { }

    public DbSet<Event> Events => Set<Event>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        var e = modelBuilder.Entity<Event>();

        e.HasKey(x => x.Id);

        // Mapeo explícito: longitudes máximas (evita columnas NVARCHAR(MAX) por defecto)
        e.Property(x => x.Source).HasMaxLength(200).IsRequired();
        e.Property(x => x.Severity).HasMaxLength(20).IsRequired();
        e.Property(x => x.Message).HasMaxLength(2000).IsRequired();
        e.Property(x => x.OccurredAt).IsRequired();
        e.Property(x => x.RecordedAt).IsRequired();

        // Índices para queries comunes: por fuente y por fecha (rendimiento)
        e.HasIndex(x => x.Source);
        e.HasIndex(x => x.OccurredAt);

        base.OnModelCreating(modelBuilder);
    }
}