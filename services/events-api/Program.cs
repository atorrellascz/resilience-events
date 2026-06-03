using Prometheus;

var builder = WebApplication.CreateBuilder(args);

var app = builder.Build();

// Automatically measures rate, errors and duration (RED) of every HTTP request.
app.UseHttpMetrics();

// Hello / service identity
app.MapGet("/", () => Results.Json(new
{
    service  = "events-api",
    language = ".NET 10 / C#",
    domain   = "operational event records",
    message  = "Hello from events-api - Phase 0 stub"
}));

// Liveness: is the process alive? (k8s restarts the pod if this fails)
app.MapGet("/health", () => Results.Json(new { status = "healthy" }));

// Readiness: ready to receive traffic? (k8s stops sending traffic if this fails)
// Phase 1: here we will check the real connection to SQL Server.
app.MapGet("/ready", () => Results.Json(new { status = "ready" }));

// Endpoint that Prometheus scrapes every 15s
app.MapMetrics();

app.Run();