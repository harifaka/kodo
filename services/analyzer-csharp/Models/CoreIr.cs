using System.Text.Json.Serialization;

namespace Kodo.Analyzer.CSharp.Models;

/// <summary>Mirror of packages/core-ir/schema.json — ComponentNode.field.</summary>
public sealed record ComponentField(
    string Name,
    string Type,
    string? Visibility,
    IReadOnlyList<string> Annotations);

/// <summary>Mirror of packages/core-ir/schema.json — ComponentNode.method.</summary>
public sealed record ComponentMethod(
    string Name,
    string? ReturnType,
    IReadOnlyList<string> Parameters);

/// <summary>Mirror of packages/core-ir/schema.json — ComponentNode.</summary>
public sealed record ComponentNode(
    string Id,
    string Name,
    string Stack,
    string Layer,
    string Kind,
    string FilePath,
    IReadOnlyList<string> Annotations,
    IReadOnlyList<ComponentField> Fields,
    IReadOnlyList<ComponentMethod> Methods);

/// <summary>Mirror of packages/core-ir/schema.json — ComponentRelation.</summary>
public sealed record ComponentRelation(string SourceId, string TargetId, string Type);

public sealed record AnalyzeRequest(
    [property: JsonPropertyName("rootPath")] string RootPath,
    [property: JsonPropertyName("files")] IReadOnlyList<string> Files);

public sealed record AnalyzeResponse(
    IReadOnlyList<ComponentNode> Nodes,
    IReadOnlyList<ComponentRelation> Relations,
    IReadOnlyList<string> Warnings);

public static class IrConstants
{
    public const string CSharpStack = "csharp-dotnet";

    public static class Layers
    {
        public const string Controller = "controller";
        public const string Service = "service";
        public const string Repository = "repository";
        public const string Entity = "entity";
        public const string ViewModel = "viewmodel";
        public const string View = "view";
        public const string Component = "component";
        public const string Other = "other";
    }

    public static class Kinds
    {
        public const string Class = "class";
        public const string Interface = "interface";
        public const string Record = "record";
        public const string Enum = "enum";
        public const string Module = "module";
    }

    public static class RelationTypes
    {
        public const string DependsOn = "depends_on";
        public const string Inherits = "inherits";
        public const string Implements = "implements";
        public const string References = "references";
    }
}
