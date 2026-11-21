namespace Kodo.Analyzer.CSharp.Models;

/// <summary>Field/property payload for a single dry-run patch operation.</summary>
public sealed record PatchField(
    string Name,
    string Type,
    string? Visibility,
    IReadOnlyList<string> Annotations);

/// <summary>One surgical edit requested by the orchestrator's dry-run endpoint.</summary>
public sealed record PatchOperation(
    string Op,
    string? TypeName,
    string? FieldName,
    string? OriginalName,
    PatchField? Field,
    string? Annotation);

/// <summary>Stateless patch request: the caller ships the file content, nothing is read from disk.</summary>
public sealed record PatchRequest(
    string? FilePath,
    string? Content,
    IReadOnlyList<PatchOperation>? Operations);

/// <summary>Proposed text plus what was applied. Nothing is written to disk.</summary>
public sealed record PatchResponse(
    string ProposedContent,
    IReadOnlyList<string> AppliedOps,
    IReadOnlyList<string> Warnings);
