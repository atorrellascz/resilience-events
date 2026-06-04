using EventsApi.Application.Dtos;
using FluentValidation;

namespace EventsApi.Application.Validation;

/// <summary>
/// Validates the HTTP INPUT (the DTO) before it reaches the domain.
/// This is defense at the boundary: we reject garbage early, with clear messages.
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

        // An event cannot have "occurred" in the future (defense against absurd data)
        RuleFor(x => x.OccurredAt)
            .Must(d => d is null || d <= DateTimeOffset.UtcNow.AddMinutes(5))
            .WithMessage("OccurredAt cannot be in the future.");
    }
}