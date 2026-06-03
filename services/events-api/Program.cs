using Prometheus;

var builder = WebApplication.CreateBuilder(args);

var app = builder.Build();

// Mide rate, errores y duración (RED) de cada request HTTP automáticamente.
app.UseHttpMetrics();

// Hello / identidad del servicio
app.MapGet("/", () => Results.Json(new
{
    service  = "events-api",
    language = ".NET 10 / C#",
    domain   = "operational event records",
    message  = "Hello from events-api - Phase 0 stub"
}));

// Liveness: ¿el proceso está vivo? (k8s reinicia el pod si esto falla)
app.MapGet("/health", () => Results.Json(new { status = "healthy" }));

// Readiness: ¿listo para recibir tráfico? (k8s deja de enviarle tráfico si falla)
// Fase 1: aquí chequearemos la conexión real a SQL Server.
app.MapGet("/ready", () => Results.Json(new { status = "ready" }));

// Endpoint que Prometheus scrapea cada 15s
app.MapMetrics();

app.Run();