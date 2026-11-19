using System.Text.RegularExpressions;
using Kodo.Analyzer.CSharp.Models;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Kodo.Analyzer.CSharp.Analysis;

public sealed record AnalysisResult(
    IReadOnlyList<ComponentNode> Nodes,
    IReadOnlyList<ComponentRelation> Relations,
    IReadOnlyList<string> Warnings);

/// <summary>
/// Syntax-only Roslyn analysis. Each file is parsed with <see cref="CSharpSyntaxTree.ParseText(string, CSharpParseOptions, string)"/>
/// and mapped onto the Core IR. No compilation, no semantic model, no writes — Phase 1 is read-only.
/// </summary>
public static class RoslynAnalyzer
{
    private const string BaseRelationMarker = "__base";

    private static readonly Regex IdentifierRegex = new("[A-Za-z_][A-Za-z0-9_]*", RegexOptions.Compiled);
    private static readonly Regex WhitespaceRegex = new("\\s+", RegexOptions.Compiled);

    private static readonly HashSet<string> NonTypeIdentifiers = new(StringComparer.Ordinal)
    {
        "void", "var", "int", "long", "short", "byte", "sbyte", "uint", "ulong", "ushort",
        "float", "double", "decimal", "bool", "char", "string", "object", "dynamic",
        "nint", "nuint", "ref", "out", "in", "params", "this", "base", "new", "readonly",
        "const", "static", "async", "await", "nullable", "notnull", "unmanaged", "where"
    };

    private static readonly string[] GeneratedFileSuffixes =
    [
        ".g.cs", ".g.i.cs", ".designer.cs", ".generated.cs", ".assemblyattributes.cs", ".assemblyinfo.cs"
    ];

    private sealed record PendingReference(string SourceId, string TargetName, string RelationType);

    private sealed class ParsedUnit
    {
        public List<ComponentNode> Nodes { get; } = [];
        public List<PendingReference> References { get; } = [];
    }

    public static AnalysisResult Analyze(string rootPath, IEnumerable<string>? files)
    {
        var warnings = new List<string>();
        var units = new List<ParsedUnit>();
        var root = Path.GetFullPath(rootPath);

        if (!Directory.Exists(root))
        {
            return new AnalysisResult([], [], [$"C# analyzer: root path does not exist: {rootPath}"]);
        }

        foreach (var candidate in (files ?? []).Where(f => !string.IsNullOrWhiteSpace(f)).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            var fullPath = Path.GetFullPath(Path.IsPathRooted(candidate) ? candidate : Path.Combine(root, candidate));

            if (!IsUnderRoot(root, fullPath))
            {
                warnings.Add($"C# analyzer: skipped '{candidate}' (outside of rootPath).");
                continue;
            }

            if (!fullPath.EndsWith(".cs", StringComparison.OrdinalIgnoreCase) || IsGeneratedFile(fullPath))
            {
                continue;
            }

            if (!File.Exists(fullPath))
            {
                warnings.Add($"C# analyzer: skipped missing file '{ToRelative(root, fullPath)}'.");
                continue;
            }

            try
            {
                var source = File.ReadAllText(fullPath);
                var tree = CSharpSyntaxTree.ParseText(
                    source,
                    new CSharpParseOptions(LanguageVersion.Latest),
                    path: fullPath);

                var unit = new ParsedUnit();
                CollectChildren(tree.GetRoot(), scope: string.Empty, ToRelative(root, fullPath), unit);
                units.Add(unit);
            }
            catch (Exception ex)
            {
                warnings.Add($"C# analyzer: failed to parse '{ToRelative(root, fullPath)}': {ex.Message}");
            }
        }

        var nodes = MergePartials(units.SelectMany(u => u.Nodes))
            .OrderBy(n => n.Stack, StringComparer.Ordinal)
            .ThenBy(n => n.FilePath, StringComparer.Ordinal)
            .ThenBy(n => n.Name, StringComparer.Ordinal)
            .ToList();

        var relations = ResolveRelations(nodes, units.SelectMany(u => u.References));
        return new AnalysisResult(nodes, relations, warnings);
    }

    private static void CollectChildren(SyntaxNode container, string scope, string relPath, ParsedUnit unit)
    {
        foreach (var child in container.ChildNodes())
        {
            switch (child)
            {
                case FileScopedNamespaceDeclarationSyntax fileScoped:
                    CollectChildren(fileScoped, Join(scope, fileScoped.Name.ToString()), relPath, unit);
                    break;
                case NamespaceDeclarationSyntax blockScoped:
                    CollectChildren(blockScoped, Join(scope, blockScoped.Name.ToString()), relPath, unit);
                    break;
                case BaseTypeDeclarationSyntax type:
                    CollectType(type, scope, relPath, unit);
                    break;
            }
        }
    }

    private static void CollectType(BaseTypeDeclarationSyntax type, string scope, string relPath, ParsedUnit unit)
    {
        var name = type.Identifier.ValueText;
        if (string.IsNullOrWhiteSpace(name))
        {
            return;
        }

        var id = Join(scope, name);
        var kind = KindOf(type);
        var annotations = FormatAttributes(type.AttributeLists);
        var fields = new List<ComponentField>();
        var methods = new List<ComponentMethod>();

        if (type is TypeDeclarationSyntax declaration)
        {
            foreach (var member in declaration.Members)
            {
                switch (member)
                {
                    case FieldDeclarationSyntax field:
                        var fieldType = NormalizeType(field.Declaration.Type.ToString());
                        var fieldAnnotations = FormatAttributes(field.AttributeLists);
                        var visibility = VisibilityOf(field.Modifiers);
                        foreach (var variable in field.Declaration.Variables)
                        {
                            fields.Add(new ComponentField(variable.Identifier.ValueText, fieldType, visibility, fieldAnnotations));
                            AddTypeReferences(unit, id, field.Declaration.Type, IrConstants.RelationTypes.DependsOn);
                        }
                        break;

                    case PropertyDeclarationSyntax property:
                        var propertyType = NormalizeType(property.Type.ToString());
                        fields.Add(new ComponentField(
                            property.Identifier.ValueText,
                            propertyType,
                            VisibilityOf(property.Modifiers),
                            FormatAttributes(property.AttributeLists)));
                        AddTypeReferences(unit, id, property.Type, IrConstants.RelationTypes.DependsOn);
                        break;

                    case ConstructorDeclarationSyntax constructor:
                        foreach (var parameter in constructor.ParameterList.Parameters)
                        {
                            if (parameter.Type is not null)
                            {
                                AddTypeReferences(unit, id, parameter.Type, IrConstants.RelationTypes.DependsOn);
                            }
                        }
                        break;

                    case MethodDeclarationSyntax method:
                        methods.Add(new ComponentMethod(
                            method.Identifier.ValueText,
                            NormalizeType(method.ReturnType.ToString()),
                            method.ParameterList.Parameters.Select(RenderParameter).ToList()));
                        AddTypeReferences(unit, id, method.ReturnType, IrConstants.RelationTypes.References);
                        foreach (var parameter in method.ParameterList.Parameters)
                        {
                            if (parameter.Type is not null)
                            {
                                AddTypeReferences(unit, id, parameter.Type, IrConstants.RelationTypes.References);
                            }
                        }
                        break;

                    case BaseTypeDeclarationSyntax nested:
                        CollectType(nested, id, relPath, unit);
                        break;
                }
            }

            // Primary constructors: `public sealed class OrderService(IOrderRepository repo)`.
            // Records are handled below because their ParameterList holds positional parameters.
            if (declaration.ParameterList is not null && declaration is not RecordDeclarationSyntax)
            {
                foreach (var parameter in declaration.ParameterList.Parameters)
                {
                    if (parameter.Type is null)
                    {
                        continue;
                    }

                    fields.Add(new ComponentField(
                        parameter.Identifier.ValueText,
                        NormalizeType(parameter.Type.ToString()),
                        "private",
                        []));
                    AddTypeReferences(unit, id, parameter.Type, IrConstants.RelationTypes.DependsOn);
                }
            }

            // Positional records: `public record OrderDto(Guid Id, string Name);`
            if (declaration is RecordDeclarationSyntax { ParameterList: not null } record)
            {
                foreach (var parameter in record.ParameterList!.Parameters)
                {
                    if (parameter.Type is null)
                    {
                        continue;
                    }

                    fields.Add(new ComponentField(
                        parameter.Identifier.ValueText,
                        NormalizeType(parameter.Type.ToString()),
                        "public",
                        []));
                    AddTypeReferences(unit, id, parameter.Type, IrConstants.RelationTypes.DependsOn);
                }
            }

            if (declaration.BaseList is not null)
            {
                foreach (var baseType in declaration.BaseList.Types)
                {
                    var baseName = LastIdentifier(baseType.Type.ToString());
                    if (!string.IsNullOrEmpty(baseName) && !NonTypeIdentifiers.Contains(baseName))
                    {
                        unit.References.Add(new PendingReference(id, baseName, BaseRelationMarker));
                    }
                }
            }
        }

        var layer = LayerInference.Infer(name, kind, relPath, annotations);
        unit.Nodes.Add(new ComponentNode(id, name, IrConstants.CSharpStack, layer, kind, relPath, annotations, fields, methods));
    }

    private static string KindOf(BaseTypeDeclarationSyntax type) => type switch
    {
        InterfaceDeclarationSyntax => IrConstants.Kinds.Interface,
        RecordDeclarationSyntax => IrConstants.Kinds.Record,
        EnumDeclarationSyntax => IrConstants.Kinds.Enum,
        _ => IrConstants.Kinds.Class
    };

    private static void AddTypeReferences(ParsedUnit unit, string sourceId, TypeSyntax typeSyntax, string relationType)
    {
        foreach (var identifier in TypeNames(typeSyntax.ToString()))
        {
            unit.References.Add(new PendingReference(sourceId, identifier, relationType));
        }
    }

    private static IEnumerable<string> TypeNames(string typeText)
    {
        foreach (Match match in IdentifierRegex.Matches(typeText))
        {
            if (NonTypeIdentifiers.Contains(match.Value))
            {
                continue;
            }

            yield return match.Value;
        }
    }

    private static IReadOnlyList<ComponentRelation> ResolveRelations(
        IReadOnlyList<ComponentNode> nodes,
        IEnumerable<PendingReference> references)
    {
        var byId = nodes.ToDictionary(n => n.Id, StringComparer.Ordinal);
        var byName = nodes
            .GroupBy(n => n.Name, StringComparer.Ordinal)
            .Where(group => group.Count() == 1)
            .ToDictionary(group => group.Key, group => group.First(), StringComparer.Ordinal);

        // One edge per (source, target): the strongest relation wins (inheritance > dependency > usage).
        var best = new Dictionary<(string Source, string Target), (int Priority, string Type)>();

        foreach (var reference in references)
        {
            ComponentNode? target = null;
            if (byId.TryGetValue(reference.TargetName, out var exact))
            {
                target = exact;
            }
            else if (byName.TryGetValue(reference.TargetName, out var bySimpleName))
            {
                target = bySimpleName;
            }

            if (target is null || target.Id == reference.SourceId)
            {
                continue;
            }

            var type = reference.RelationType == BaseRelationMarker
                ? (target.Kind == IrConstants.Kinds.Interface && byId[reference.SourceId].Kind != IrConstants.Kinds.Interface
                    ? IrConstants.RelationTypes.Implements
                    : IrConstants.RelationTypes.Inherits)
                : reference.RelationType;

            var priority = type switch
            {
                IrConstants.RelationTypes.Inherits or IrConstants.RelationTypes.Implements => 0,
                IrConstants.RelationTypes.DependsOn => 1,
                _ => 2
            };

            var key = (reference.SourceId, target.Id);
            if (!best.TryGetValue(key, out var existing) || priority < existing.Priority)
            {
                best[key] = (priority, type);
            }
        }

        return best
            .Select(entry => new ComponentRelation(entry.Key.Source, entry.Key.Target, entry.Value.Type))
            .OrderBy(r => r.SourceId, StringComparer.Ordinal)
            .ThenBy(r => r.Type, StringComparer.Ordinal)
            .ThenBy(r => r.TargetId, StringComparer.Ordinal)
            .ToList();
    }

    private static IEnumerable<ComponentNode> MergePartials(IEnumerable<ComponentNode> nodes)
    {
        foreach (var group in nodes.GroupBy(n => n.Id, StringComparer.Ordinal))
        {
            var merged = group.First();
            foreach (var partial in group.Skip(1))
            {
                merged = merged with
                {
                    Annotations = merged.Annotations
                        .Union(partial.Annotations, StringComparer.Ordinal)
                        .OrderBy(a => a, StringComparer.Ordinal)
                        .ToList(),
                    Fields = merged.Fields
                        .Concat(partial.Fields)
                        .GroupBy(f => f.Name, StringComparer.Ordinal)
                        .Select(g => g.First())
                        .ToList(),
                    Methods = merged.Methods
                        .Concat(partial.Methods)
                        .GroupBy(m => $"{m.Name}({string.Join(",", m.Parameters)})", StringComparer.Ordinal)
                        .Select(g => g.First())
                        .ToList()
                };
            }

            yield return merged;
        }
    }

    private static IReadOnlyList<string> FormatAttributes(SyntaxList<AttributeListSyntax> attributeLists)
    {
        var annotations = new List<string>();
        foreach (var list in attributeLists)
        {
            foreach (var attribute in list.Attributes)
            {
                var name = AttributeName(attribute.Name);
                if (!string.IsNullOrEmpty(name))
                {
                    annotations.Add($"[{name}]");
                }
            }
        }

        return annotations.Distinct(StringComparer.Ordinal).OrderBy(a => a, StringComparer.Ordinal).ToList();
    }

    private static string AttributeName(NameSyntax name)
    {
        var text = name switch
        {
            QualifiedNameSyntax qualified => qualified.Right.Identifier.ValueText,
            AliasQualifiedNameSyntax alias => alias.Name.Identifier.ValueText,
            SimpleNameSyntax simple => simple.Identifier.ValueText,
            _ => name.ToString()
        };

        return text.EndsWith("Attribute", StringComparison.Ordinal) ? text[..^"Attribute".Length] : text;
    }

    private static string RenderParameter(ParameterSyntax parameter)
    {
        var type = parameter.Type is null ? string.Empty : NormalizeType(parameter.Type.ToString());
        return $"{type} {parameter.Identifier.ValueText}".Trim();
    }

    private static string NormalizeType(string type) => WhitespaceRegex.Replace(type, " ").Trim();

    private static string VisibilityOf(SyntaxTokenList modifiers)
    {
        foreach (var modifier in modifiers)
        {
            var text = modifier.ValueText;
            if (text is "public" or "private" or "protected" or "internal")
            {
                return text;
            }
        }

        return "private";
    }

    private static string LastIdentifier(string typeText)
    {
        string? last = null;
        foreach (Match match in IdentifierRegex.Matches(typeText))
        {
            last = match.Value;
        }

        return last ?? string.Empty;
    }

    private static string Join(string scope, string name) => scope.Length == 0 ? name : $"{scope}.{name}";

    private static bool IsGeneratedFile(string path)
    {
        var fileName = Path.GetFileName(path);
        return GeneratedFileSuffixes.Any(suffix => fileName.EndsWith(suffix, StringComparison.OrdinalIgnoreCase));
    }

    private static bool IsUnderRoot(string root, string candidate)
    {
        var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        if (string.Equals(root, candidate, comparison))
        {
            return true;
        }

        var normalizedRoot = root.EndsWith(Path.DirectorySeparatorChar) ? root : root + Path.DirectorySeparatorChar;
        return candidate.StartsWith(normalizedRoot, comparison);
    }

    private static string ToRelative(string root, string path) =>
        Path.GetRelativePath(root, path).Replace('\\', '/');
}
