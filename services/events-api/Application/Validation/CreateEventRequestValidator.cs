using EventsApi.Application.Dtos;
using FluentValidation;

namespace EventsApi.Application.Validation;

/// <summary>
/// Valida la ENTRADA HTTP (el DTO) antes de que llegue al dominio.
/// Esto es defensa en la frontera: rechazamos basura temprano, con mensajes claros.
/// </summary>
public class CreateEventRequestValidator : AbstractValidator<CreateEventRequest>
{
    private static readonly string[] AllowedSeverities = { "info", "warning", "critical" };

    public CreateEventRequestValidator()
    {
        RuleFor(x => x.Source)
            .NotEmpty().WithMessage("Source is required.")
            .MaximumLength(200);

        RuleFor(x => x.Message)
            .NotEmpty().WithMessage("Message is required.")
            .MaximumLength(2000);

        RuleFor(x => x.Severity)
            .Must(s => AllowedSeverities.Contains((s ?? "").ToLowerInvariant()))
            .WithMessage("Severity must be one of: info, warning, critical.");

        // Un evento no puede haber "ocurrido" en el futuro (defensa contra datos absurdos)
        RuleFor(x => x.OccurredAt)
            .Must(d => d is null || d <= DateTimeOffset.UtcNow.AddMinutes(5))
            .WithMessage("OccurredAt cannot be in the future.");
    }
}