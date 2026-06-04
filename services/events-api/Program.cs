using EventsApi.Application.Interfaces;
using EventsApi.Application.Services;
using EventsApi.Infrastructure.Persistence;
using EventsApi.Infrastructure.Repositories;
using FluentValidation;
using FluentValidation.AspNetCore;
using Microsoft.EntityFrameworkCore;
using Prometheus;
using Serilog;

var builder = WebApplication.CreateBuilder(args);

// ── Structured logging (JSON) with Serilog → consumed by Loki in Phase 3 ──
builder.Host.UseSerilog((ctx, cfg) => cfg
    .ReadFrom.Configuration(ctx.Configuration)
    .Enrich.FromLogContext()
    .WriteTo.Console(new Serilog.Formatting.Json.JsonFormatter()));

// ── Dependency registration (Composition Root): the layers are wired here ──

// DbContext → SQL Server, connection string from config/environment (12-factor)
builder.Services.AddDbContext<EventsDbContext>(opt =>
    opt.UseSqlServer(builder.Configuration.GetConnectionString("Sql")));

// The D in SOLID as config: the interface resolves to the concrete implementation.
// Switching from EF Core to something else = changing ONLY these two lines.
builder.Services.AddScoped<IEventRepository, EventRepository>();
builder.Services.AddScoped<IEventService, EventService>();

builder.Services.AddControllers();

builder.Services.AddValidatorsFromAssemblyContaining<EventsApi.Application.Validation.CreateEventRequestValidator>();
builder.Services.AddFluentValidationAutoValidation();

var app = builder.Build();

// Measures RED (rate/errors/duration) of every HTTP request.
app.UseHttpMetrics();
app.UseSerilogRequestLogging();   // one structured log per request (method, path, status, duration)

app.MapControllers();

// ── Health endpoints ──
// Liveness: is the process alive? Cheap, does NOT touch the DB (if this fails, k8s restarts).
app.MapGet("/health", () => Results.Json(new { status = "healthy" }));

// REAL readiness: can I serve traffic? Checks that SQL Server responds.
// If the DB goes down, /ready fails → k8s removes the pod from the load balancer (does not kill it).
app.MapGet("/ready", async (IEventRepository repo, CancellationToken ct) =>
{
    var dbOk = await repo.CanConnectAsync(ct);
    return dbOk
        ? Results.Json(new { status = "ready" })
        : Results.Json(new { status = "not-ready", reason = "database unreachable" },
                       statusCode: StatusCodes.Status503ServiceUnavailable);
});

app.MapMetrics();   // /metrics for Prometheus

await ApplyMigrationsWithRetryAsync(app);


app.Run();

static async Task ApplyMigrationsWithRetryAsync(WebApplication app)
{
    const int maxAttempts = 10;
    var logger = app.Services.GetRequiredService<ILogger<Program>>();

    for (var attempt = 1; attempt <= maxAttempts; attempt++)
    {
        try
        {
            using var scope = app.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<EventsDbContext>();
            await db.Database.MigrateAsync();
            logger.LogInformation("Migrations applied successfully on attempt {Attempt}", attempt);
            return;
        }
        catch (Exception ex)
        {
            // Linear backoff: 2s, 4s, 6s... gives SQL Server time to finish starting up.
            var delay = TimeSpan.FromSeconds(2 * attempt);
            logger.LogWarning(ex,
                "Migration attempt {Attempt}/{Max} failed; retrying in {Delay}s",
                attempt, maxAttempts, delay.TotalSeconds);
            await Task.Delay(delay);
        }
    }

    // If it could not be done after all attempts, we fail explicitly (don't start up blind).
    logger.LogError("Could not apply migrations after {Max} attempts; shutting down", maxAttempts);
    throw new InvalidOperationException("Database migration failed after retries.");
}