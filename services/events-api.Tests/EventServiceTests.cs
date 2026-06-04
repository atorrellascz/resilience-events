using EventsApi.Application.Dtos;
using EventsApi.Application.Interfaces;
using EventsApi.Application.Services;
using EventsApi.Domain.Entities;
using FluentAssertions;
using Moq;
using Xunit;

namespace EventsApi.Tests;

public class EventServiceTests
{
    private readonly Mock<IEventRepository> _repo = new();
    private readonly EventService _sut;   // sut = System Under Test

    public EventServiceTests()
    {
        // Inyectamos el MOCK en vez del repo real de EF Core. Sin SQL Server.
        _sut = new EventService(_repo.Object);
    }

    [Fact]
    public async Task CreateAsync_ValidRequest_PersistsAndReturnsResponse()
    {
        // Arrange: el mock devuelve lo que se le pase a AddAsync
        _repo.Setup(r => r.AddAsync(It.IsAny<Event>(), It.IsAny<CancellationToken>()))
             .ReturnsAsync((Event e, CancellationToken _) => e);

        var req = new CreateEventRequest("payment-api", "critical", "pool exhausted", null);

        // Act
        var result = await _sut.CreateAsync(req);

        // Assert
        result.Should().NotBeNull();
        result.Source.Should().Be("payment-api");
        result.Severity.Should().Be("critical");
        result.Id.Should().NotBe(Guid.Empty);            // el dominio generó un Id
        _repo.Verify(r => r.AddAsync(It.IsAny<Event>(), It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task CreateAsync_UnknownSeverity_NormalizesToInfo()
    {
        // El dominio normaliza severities desconocidas a "info" (regla de negocio)
        _repo.Setup(r => r.AddAsync(It.IsAny<Event>(), It.IsAny<CancellationToken>()))
             .ReturnsAsync((Event e, CancellationToken _) => e);

        var req = new CreateEventRequest("svc", "weird-value", "msg", null);

        var result = await _sut.CreateAsync(req);

        result.Severity.Should().Be("info");
    }

    [Fact]
    public async Task GetAsync_NotFound_ReturnsNull()
    {
        _repo.Setup(r => r.GetByIdAsync(It.IsAny<Guid>(), It.IsAny<CancellationToken>()))
             .ReturnsAsync((Event?)null);

        var result = await _sut.GetAsync(Guid.NewGuid());

        result.Should().BeNull();
    }

    [Theory]
    [InlineData(0, 50)]      // límite inválido (0) → se corrige a 50
    [InlineData(-5, 50)]     // negativo → 50
    [InlineData(999, 50)]    // demasiado alto → 50
    [InlineData(25, 25)]     // válido → se respeta
    public async Task ListAsync_ClampsLimitToSafeRange(int requested, int expectedUsed)
    {
        _repo.Setup(r => r.ListAsync(It.IsAny<int>(), It.IsAny<CancellationToken>()))
             .ReturnsAsync(new List<Event>());

        await _sut.ListAsync(requested);

        // Verificamos que el service llamó al repo con el límite ACOTADO, no el pedido
        _repo.Verify(r => r.ListAsync(expectedUsed, It.IsAny<CancellationToken>()), Times.Once);
    }
}