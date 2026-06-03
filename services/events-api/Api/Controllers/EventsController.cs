using EventsApi.Application.Dtos;
using EventsApi.Application.Services;
using Microsoft.AspNetCore.Mvc;

namespace EventsApi.Api.Controllers;

[ApiController]
[Route("api/events")]
public class EventsController : ControllerBase
{
    private readonly IEventService _service;
    private readonly ILogger<EventsController> _logger;

    // DI inyecta el servicio y el logger. El controller no sabe de SQL ni de EF.
    public EventsController(IEventService service, ILogger<EventsController> logger)
    {
        _service = service;
        _logger = logger;
    }

    /// <summary>Crea un event record.</summary>
    [HttpPost]
    public async Task<ActionResult<EventResponse>> Create(
        [FromBody] CreateEventRequest req, CancellationToken ct)
    {
        var created = await _service.CreateAsync(req, ct);
        // Logging estructurado: 'EventId' es un campo, no texto interpolado.
        _logger.LogInformation("Event created {EventId} from {Source} severity {Severity}",
            created.Id, created.Source, created.Severity);
        // 201 Created + Location header apuntando al recurso nuevo (REST correcto).
        return CreatedAtAction(nameof(GetById), new { id = created.Id }, created);
    }

    /// <summary>Obtiene un event record por id.</summary>
    [HttpGet("{id:guid}")]
    public async Task<ActionResult<EventResponse>> GetById(Guid id, CancellationToken ct)
    {
        var evt = await _service.GetAsync(id, ct);
        return evt is null ? NotFound() : Ok(evt);   // 404 si no existe, 200 si sí
    }

    /// <summary>Lista los últimos event records.</summary>
    [HttpGet]
    public async Task<ActionResult<IReadOnlyList<EventResponse>>> List(
        [FromQuery] int limit = 50, CancellationToken ct = default)
    {
        var events = await _service.ListAsync(limit, ct);
        return Ok(events);
    }
}