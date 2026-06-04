using EventsApi.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace EventsApi.Infrastructure.Persistence;

/// <summary>
/// Bridge between the domain and SQL Server. Lives in Infrastructure because
/// it knows EF Core — a detail the domain must never see.
/// </summary>
public class EventsDbContext : DbContext
{
    public EventsDbContext(DbContextOptions<EventsDbContext> options) : base(options) { }

    public DbSet<Event> Events => Set<Event>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        var e = modelBuilder.Entity<Event>();

        e.HasKey(x => x.Id);

        // Explicit mapping: maximum lengths (avoids default NVARCHAR(MAX) columns)
        e.Property(x => x.Source).HasMaxLength(200).IsRequired();
        e.Property(x => x.Severity).HasMaxLength(20).IsRequired();
        e.Property(x => x.Message).HasMaxLength(2000).IsRequired();
        e.Property(x => x.OccurredAt).IsRequired();
        e.Property(x => x.RecordedAt).IsRequired();

        // Indexes for common queries: by source and by date (performance)
        e.HasIndex(x => x.Source);
        e.HasIndex(x => x.OccurredAt);

        base.OnModelCreating(modelBuilder);
    }
}