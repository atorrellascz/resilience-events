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

    // DI injects the service and the logger. The controller knows nothing about SQL or EF.
    public EventsController(IEventService service, ILogger<EventsController> logger)
    {
        _service = service;
        _logger = logger;
    }

    /// <summary>Creates an event record.</summary>
    [HttpPost]
    public async Task<ActionResult<EventResponse>> Create(
        [FromBody] CreateEventRequest req, CancellationToken ct)
    {
        var created = await _service.CreateAsync(req, ct);
        // Structured logging: 'EventId' is a field, not interpolated text.
        _logger.LogInformation("Event created {EventId} from {Source} severity {Severity}",
            created.Id, created.Source, created.Severity);
        // 201 Created + Location header pointing to the new resource (correct REST).
        return CreatedAtAction(nameof(GetById), new { id = created.Id }, created);
    }

    /// <summary>Gets an event record by id.</summary>
    [HttpGet("{id:guid}")]
    public async Task<ActionResult<EventResponse>> GetById(Guid id, CancellationToken ct)
    {
        var evt = await _service.GetAsync(id, ct);
        return evt is null ? NotFound() : Ok(evt);   // 404 if it doesn't exist, 200 if it does
    }

    /// <summary>Lists the most recent event records.</summary>
    [HttpGet]
    public async Task<ActionResult<IReadOnlyList<EventResponse>>> List(
        [FromQuery] int limit = 50, CancellationToken ct = default)
    {
        var events = await _service.ListAsync(limit, ct);
        return Ok(events);
    }
}