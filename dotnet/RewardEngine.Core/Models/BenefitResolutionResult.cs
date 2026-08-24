namespace RewardEngine.Core.Models;

public record BenefitResolutionResult
{
    public string? ResolvedProgram { get; init; }
    public IReadOnlyList<string>? ResolvedPrograms { get; init; }
    public required bool RequiresManualVerification { get; init; }
    public string? VerificationReason { get; init; }
}