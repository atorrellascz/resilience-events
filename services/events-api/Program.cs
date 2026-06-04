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

// ── Logging estructurado (JSON) con Serilog → lo consumirá Loki en Fase 3 ──
builder.Host.UseSerilog((ctx, cfg) => cfg
    .ReadFrom.Configuration(ctx.Configuration)
    .Enrich.FromLogContext()
    .WriteTo.Console(new Serilog.Formatting.Json.JsonFormatter()));

// ── Registro de dependencias (Composition Root): aquí se atan las capas ──

// DbContext → SQL Server, cadena de conexión desde config/entorno (12-factor)
builder.Services.AddDbContext<EventsDbContext>(opt =>
    opt.UseSqlServer(builder.Configuration.GetConnectionString("Sql")));

// La D de SOLID hecha config: la interfaz se resuelve a la implementación concreta.
// Cambiar de EF Core a otra cosa = cambiar SOLO estas dos líneas.
builder.Services.AddScoped<IEventRepository, EventRepository>();
builder.Services.AddScoped<IEventService, EventService>();

builder.Services.AddControllers();

builder.Services.AddValidatorsFromAssemblyContaining<EventsApi.Application.Validation.CreateEventRequestValidator>();
builder.Services.AddFluentValidationAutoValidation();

var app = builder.Build();

// Mide RED (rate/errors/duration) de cada request HTTP.
app.UseHttpMetrics();
app.UseSerilogRequestLogging();   // un log estructurado por request (método, ruta, status, duración)

app.MapControllers();

// ── Health endpoints ──
// Liveness: ¿el proceso vive? Barato, NO toca la DB (si fallara aquí, k8s reinicia).
app.MapGet("/health", () => Results.Json(new { status = "healthy" }));

// Readiness REAL: ¿puedo atender tráfico? Comprueba que SQL Server responde.
// Si la DB cae, /ready falla → k8s saca el pod del balanceo (no lo mata).
app.MapGet("/ready", async (IEventRepository repo, CancellationToken ct) =>
{
    var dbOk = await repo.CanConnectAsync(ct);
    return dbOk
        ? Results.Json(new { status = "ready" })
        : Results.Json(new { status = "not-ready", reason = "database unreachable" },
                       statusCode: StatusCodes.Status503ServiceUnavailable);
});

app.MapMetrics();   // /metrics para Prometheus

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
            // Backoff lineal: 2s, 4s, 6s... da tiempo a que SQL Server termine de arrancar.
            var delay = TimeSpan.FromSeconds(2 * attempt);
            logger.LogWarning(ex,
                "Migration attempt {Attempt}/{Max} failed; retrying in {Delay}s",
                attempt, maxAttempts, delay.TotalSeconds);
            await Task.Delay(delay);
        }
    }

    // Si tras todos los intentos no se pudo, fallamos explícitamente (no arrancar a ciegas).
    logger.LogError("Could not apply migrations after {Max} attempts; shutting down", maxAttempts);
    throw new InvalidOperationException("Database migration failed after retries.");
}